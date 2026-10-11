// Browser-side cryptography only. No private key is sent to the server.
export const PROTOCOL = "HumanGrant Protocol 0.1 Draft";
const encoder = new TextEncoder();
export const b64 = bytes => btoa(String.fromCharCode(...bytes));
export const b64u = bytes => b64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export function unb64u(value, length) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Invalid key encoding.");
  const bytes = Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4)), c => c.charCodeAt(0));
  if (bytes.length !== length || b64u(bytes) !== value) throw new Error("Invalid key length.");
  return bytes;
}
const digest = async bytes => new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
export async function generateIdentity() {
  const pair = await crypto.subtle.generateKey({name: "Ed25519"}, false, ["sign", "verify"]);
  const publicKey = b64u(new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey)));
  return {privateKey: pair.privateKey, publicKey, keyId: "ed25519:" + b64u(await digest(unb64u(publicKey, 32)))};
}
export async function importIdentity(data) {
  if (data.format !== "humangrant-key-v1") throw new Error("Use a HumanGrant identity file.");
  const prefix = Uint8Array.from([0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20]);
  const pkcs8 = new Uint8Array(48);
  pkcs8.set(prefix); pkcs8.set(unb64u(data.private_key, 32), 16);
  const privateKey = await crypto.subtle.importKey("pkcs8", pkcs8, {name: "Ed25519"}, false, ["sign"]);
  const publicBytes = unb64u(data.public_key, 32);
  const verifier = await crypto.subtle.importKey("raw", publicBytes, "Ed25519", false, ["verify"]);
  const probe = encoder.encode("HumanGrant local identity consistency check");
  const proof = await crypto.subtle.sign("Ed25519", privateKey, probe);
  if (!await crypto.subtle.verify("Ed25519", verifier, proof, probe)) throw new Error("Public and private keys do not match.");
  return {privateKey, publicKey: data.public_key, keyId: "ed25519:" + b64u(await digest(publicBytes))};
}
export async function signedHeaders(identity, method, target, body, token = "anonymous", created = Math.floor(Date.now()/1000), nonce = b64u(crypto.getRandomValues(new Uint8Array(24)))) {
  unb64u(nonce, 24);
  if (!Number.isInteger(created) || created < 0) throw new Error("Invalid signature time.");
  if (token !== "anonymous") unb64u(token, 32);
  const contentDigest = "sha-256=:" + b64(await digest(encoder.encode(body))) + ":";
  const authorization = "HumanGrant " + token;
  const components = '("@method" "@target-uri" "content-digest" "content-type" "x-hg-key" "authorization")';
  const params = `${components};created=${created};expires=${created+60};nonce="${nonce}";keyid="${identity.keyId}";alg="ed25519";tag="humangrant-0.1"`;
  const base = [`"@method": ${method}`, `"@target-uri": ${target}`, `"content-digest": ${contentDigest}`, '"content-type": application/json', `"x-hg-key": ${identity.publicKey}`, `"authorization": ${authorization}`, `"@signature-params": ${params}`].join("\n");
  const signature = b64(new Uint8Array(await crypto.subtle.sign("Ed25519", identity.privateKey, encoder.encode(base))));
  return {"Content-Type": "application/json", "Content-Digest": contentDigest, "X-HG-Key": identity.publicKey, "Authorization": authorization, "Signature-Input": "hg=" + params, "Signature": "hg=:" + signature + ":"};
}
export async function signHuman(identity, challenge, origin, requestId) {
  const parsed = JSON.parse(challenge), now = Math.floor(Date.now()/1000);
  if (!Array.isArray(parsed) || parsed.length !== 6 || parsed[0] !== "HumanGrant human authentication 0.1" || parsed[1] !== origin || parsed[2] !== requestId || JSON.stringify(parsed) !== challenge || !Number.isInteger(parsed[5]) || parsed.slice(2,5).some(value => typeof value !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(value)) || parsed[5] <= now || parsed[5] > now+150) throw new Error("The challenge does not match this request and trusted origin.");
  return {public_key: identity.publicKey, signature: b64(new Uint8Array(await crypto.subtle.sign("Ed25519", identity.privateKey, encoder.encode(challenge))))};
}
export function parseMarkdown(text) {
  const state = {};
  for (const line of text.split("\n")) {
    const match = line.match(/^([a-z_]+): (.+)$/);
    if (!match) continue;
    if (Object.hasOwn(state, match[1])) throw new Error("Duplicate state field.");
    state[match[1]] = JSON.parse(match[2]);
  }
  const required = ["protocol_version", "request_id", "status", "status_text", "phase", "created_at", "status_updated_at", "checked_at", "expires_at", "poll_after_seconds", "human_authorization_url", "requested_permissions", "email_request_status", "email_retry_after_seconds"];
  const phases = ["waiting_human", "authenticating_human", "awaiting_consent", "approved", "succeeded", "rejected", "cancelled", "expired"];
  if (required.some(key => !Object.hasOwn(state,key)) || state.protocol_version !== PROTOCOL || !phases.includes(state.phase)) throw new Error("Unknown state representation.");
  for (const field of ["created_at", "status_updated_at", "checked_at", "expires_at", "poll_after_seconds", "email_retry_after_seconds"]) {
    if (!Number.isInteger(state[field]) || state[field] < 0) throw new Error("Invalid state time.");
  }
  return state;
}
