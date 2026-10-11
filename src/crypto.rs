use crate::error::{Error, Result};
use base64::{engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD}, Engine as _};
use ed25519_dalek::{Signature, VerifyingKey};
use hmac::{Hmac, Mac};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub const COMPONENTS: &str = "(\"@method\" \"@target-uri\" \"content-digest\" \"content-type\" \"x-hg-key\" \"authorization\")";

pub fn random_token() -> String {
    let mut bytes=[0u8;32];
    OsRng.fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}

pub fn hash(bytes: &[u8]) -> String { URL_SAFE_NO_PAD.encode(Sha256::digest(bytes)) }

pub fn private_hash(secret: &[u8], value: &str) -> Result<String> {
    let mut mac=Hmac::<Sha256>::new_from_slice(secret).map_err(|_| Error::internal())?;
    mac.update(value.as_bytes());
    Ok(URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()))
}

pub fn public_key(encoded: &str) -> Result<VerifyingKey> {
    let bytes=URL_SAFE_NO_PAD.decode(encoded).map_err(|_| bad_signature())?;
    if URL_SAFE_NO_PAD.encode(&bytes)!=encoded { return Err(bad_signature()); }
    let array: [u8;32]=bytes.try_into().map_err(|_| bad_signature())?;
    VerifyingKey::from_bytes(&array).map_err(|_| bad_signature())
}

pub fn key_id(encoded: &str) -> Result<String> {
    Ok(format!("ed25519:{}", hash(public_key(encoded)?.as_bytes())))
}

pub fn bad_signature() -> Error {
    Error::new(401,"invalid_signature","A valid, unexpired request signature is required.")
}

pub fn verify_detached(public: &str, message: &[u8], signature: &str) -> Result<()> {
    let bytes=STANDARD.decode(signature).map_err(|_| bad_signature())?;
    if STANDARD.encode(&bytes)!=signature { return Err(bad_signature()); }
    let signature=Signature::from_slice(&bytes).map_err(|_| bad_signature())?;
    public_key(public)?.verify_strict(message,&signature).map_err(|_| bad_signature())
}

pub struct Proof {
    pub actor_id: String,
    pub public_key: String,
    pub nonce: String,
    pub expires_at: i64,
    pub authorization: String,
}

pub fn signature_params(created: i64, expires: i64, nonce: &str, key: &str) -> String {
    format!("{COMPONENTS};created={created};expires={expires};nonce=\"{nonce}\";keyid=\"{key}\";alg=\"ed25519\";tag=\"humangrant-0.1\"")
}

pub fn signature_base(method: &str, target: &str, digest: &str, public: &str,
    authorization: &str, params: &str) -> String
{
    format!("\"@method\": {method}\n\"@target-uri\": {target}\n\"content-digest\": {digest}\n\"content-type\": application/json\n\"x-hg-key\": {public}\n\"authorization\": {authorization}\n\"@signature-params\": {params}")
}

pub fn verify_http(method: &str, path: &str, headers: &BTreeMap<String,String>, body: &[u8],
    origin: &str, now: i64) -> Result<Proof>
{
    let get=|name: &str| headers.get(name).map(String::as_str).ok_or_else(bad_signature);
    if get("content-type")? != "application/json" { return Err(bad_signature()); }
    let public=get("x-hg-key")?;
    let actor=key_id(public)?;
    let digest=format!("sha-256=:{}:",STANDARD.encode(Sha256::digest(body)));
    if get("content-digest")? != digest { return Err(bad_signature()); }
    let input=get("signature-input")?;
    let prefix=format!("hg={COMPONENTS};created=");
    let rest=input.strip_prefix(prefix.as_str()).ok_or_else(bad_signature)?;
    let (created,rest)=rest.split_once(";expires=").ok_or_else(bad_signature)?;
    let (expires,rest)=rest.split_once(";nonce=\"").ok_or_else(bad_signature)?;
    let (nonce,rest)=rest.split_once("\";keyid=\"").ok_or_else(bad_signature)?;
    let (supplied_id,end)=rest.split_once("\";alg=\"ed25519\";tag=\"humangrant-0.1\"").ok_or_else(bad_signature)?;
    let created: i64=created.parse().map_err(|_| bad_signature())?;
    let expires: i64=expires.parse().map_err(|_| bad_signature())?;
    let lifetime=expires.checked_sub(created).ok_or_else(bad_signature)?;
    if !end.is_empty() || supplied_id!=actor || created>now.saturating_add(30)
        || expires<=now || !(1..=60).contains(&lifetime) || created<0
    { return Err(bad_signature()); }
    let nonce_bytes=URL_SAFE_NO_PAD.decode(nonce).map_err(|_| bad_signature())?;
    if nonce_bytes.len()!=24 || URL_SAFE_NO_PAD.encode(&nonce_bytes)!=nonce { return Err(bad_signature()); }
    let params=signature_params(created,expires,nonce,&actor);
    if input!=format!("hg={params}") { return Err(bad_signature()); }
    let authorization=get("authorization")?;
    let token=authorization.strip_prefix("HumanGrant ").ok_or_else(bad_signature)?;
    if token!="anonymous" {
        let bytes=URL_SAFE_NO_PAD.decode(token).map_err(|_| bad_signature())?;
        if bytes.len()!=32 || URL_SAFE_NO_PAD.encode(bytes)!=token { return Err(bad_signature()); }
    }
    let signature=get("signature")?.strip_prefix("hg=:").and_then(|s| s.strip_suffix(':')).ok_or_else(bad_signature)?;
    let target=format!("{origin}{path}");
    let base=signature_base(method,&target,&digest,public,authorization,&params);
    verify_detached(public,base.as_bytes(),signature)?;
    Ok(Proof { actor_id: actor, public_key: public.into(), nonce: nonce.into(), expires_at: expires,
        authorization: token.into() })
}
