use crate::auth::{HumanAuthenticator, PublicKeyAuthenticator};
use crate::config::Config;
use crate::db::{self, Clock, Store};
use crate::error::{Error, Result};
use crate::human::{self, BrowserWrite};
use crate::model::{Approval, CreateRequest, EmailRequest, Empty, NoteUpdate, Verification};
use crate::{crypto, mail, requests};
use serde::de::DeserializeOwned;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::sync::Arc;

pub struct HttpInput {
    pub method: String,
    pub path: String,
    pub headers: BTreeMap<String, String>,
    pub body: Vec<u8>,
    /// The actual socket peer's IP, never an untrusted forwarding header.
    pub source: String,
}

impl HttpInput {
    pub fn header(&self, name: &str) -> &str {
        self.headers.get(name).map(String::as_str).unwrap_or("")
    }
    fn json<T: DeserializeOwned>(&self) -> Result<T> {
        if self.header("content-type") != "application/json" {
            return Err(Error::invalid());
        }
        Ok(serde_json::from_slice(&self.body)?)
    }
}

pub struct HttpOutput {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: Vec<u8>,
}

impl HttpOutput {
    pub fn text(status: u16, mime: &str, text: &str) -> Self {
        let headers=BTreeMap::from([
            ("Content-Type".into(),mime.into()),("Cache-Control".into(),"no-store".into()),
            ("Pragma".into(),"no-cache".into()),("Referrer-Policy".into(),"no-referrer".into()),
            ("X-Content-Type-Options".into(),"nosniff".into()),
            ("Content-Security-Policy".into(),"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'".into()),
            ("X-Frame-Options".into(),"DENY".into()),
        ]);
        Self {
            status,
            headers,
            body: text.as_bytes().to_vec(),
        }
    }
    pub fn json(status: u16, value: Value) -> Result<Self> {
        Ok(Self::text(
            status,
            "application/json; charset=utf-8",
            &serde_json::to_string(&value)?,
        ))
    }
    pub fn error(error: Error) -> Self {
        let body = json!({"error":error.error,"message":error.message,"retry_after_seconds":error.retry_after_seconds});
        let mut response = Self::text(
            error.status,
            "application/json; charset=utf-8",
            &body.to_string(),
        );
        if error.retry_after_seconds > 0 {
            response
                .headers
                .insert("Retry-After".into(), error.retry_after_seconds.to_string());
        }
        response
    }
    fn page(data: Value, cookie: Option<String>) -> Result<Self> {
        let escaped = serde_json::to_string(&data)?
            .replace('&', "\\u0026")
            .replace('<', "\\u003c")
            .replace('>', "\\u003e");
        let text = include_str!("../examples/web/index.html").replace("__HG_DATA__", &escaped);
        let mut response = Self::text(200, "text/html; charset=utf-8", &text);
        if let Some(cookie) = cookie {
            response.headers.insert("Set-Cookie".into(), cookie);
        }
        Ok(response)
    }
}

pub struct App {
    pub config: Config,
    pub store: Store,
    authenticator: Box<dyn HumanAuthenticator>,
}

impl App {
    pub fn new(config: Config, clock: Arc<dyn Clock>) -> Result<Self> {
        Self::with_authenticator(config, clock, Box::new(PublicKeyAuthenticator))
    }

    pub fn with_authenticator(
        config: Config,
        clock: Arc<dyn Clock>,
        authenticator: Box<dyn HumanAuthenticator>,
    ) -> Result<Self> {
        config.validate()?;
        let store = Store::open(&config, clock)?;
        Ok(Self {
            config,
            store,
            authenticator,
        })
    }

    pub fn handle(&mut self, request: HttpInput) -> HttpOutput {
        let mut response = match self.dispatch(&request) {
            Ok(response) => response,
            Err(error) => HttpOutput::error(error),
        };
        if self.config.public_origin.starts_with("https://") {
            response.headers.insert(
                "Strict-Transport-Security".into(),
                "max-age=31536000".into(),
            );
        }
        response
    }

    fn dispatch(&mut self, request: &HttpInput) -> Result<HttpOutput> {
        if request.body.len() > 16_384 {
            return Err(Error::new(
                413,
                "body_too_large",
                "The request body is too large.",
            ));
        }
        if !request.path.starts_with('/')
            || request.path.len() > 512
            || request.path.contains(['?', '%', '\\'])
            || request.path.contains("//")
            || (request.path.len() > 1 && request.path.ends_with('/'))
            || (request.method == "GET" && !request.body.is_empty())
        {
            return Err(Error::invalid());
        }
        if request.method == "GET" {
            let asset = match request.path.as_str() {
                "/spec/v0.1.md" => Some((
                    "text/markdown; charset=utf-8",
                    include_str!("../spec/v0.1.md"),
                )),
                "/openapi.yaml" => Some((
                    "application/yaml; charset=utf-8",
                    include_str!("../openapi.yaml"),
                )),
                "/schemas/protocol.json" => Some((
                    "application/json; charset=utf-8",
                    include_str!("../schemas/protocol.json"),
                )),
                "/assets/style.css" => Some((
                    "text/css; charset=utf-8",
                    include_str!("../examples/web/style.css"),
                )),
                "/assets/ui.js" => Some((
                    "text/javascript; charset=utf-8",
                    include_str!("../examples/web/ui.js"),
                )),
                "/assets/webcrypto.js" => Some((
                    "text/javascript; charset=utf-8",
                    include_str!("../examples/web/webcrypto.js"),
                )),
                "/assets/mark.svg" => Some(("image/svg+xml", include_str!("../assets/mark.svg"))),
                "/assets/continue-with-human-beings.svg" => Some((
                    "image/svg+xml",
                    include_str!("../assets/continue-with-human-beings.svg"),
                )),
                _ => None,
            };
            if let Some((mime, text)) = asset {
                return Ok(HttpOutput::text(200, mime, text));
            }
            if request.path == "/" {
                return HttpOutput::page(
                    json!({"view":"agent","origin":self.config.public_origin,
                    "protocol_version":crate::model::PROTOCOL}),
                    None,
                );
            }
        }
        if request.path.starts_with("/v1/") {
            return self.signed(request);
        }
        self.browser(request)
    }

    fn signed(&mut self, request: &HttpInput) -> Result<HttpOutput> {
        let proof = crypto::verify_http(
            &request.method,
            &request.path,
            &request.headers,
            &request.body,
            &self.config.public_origin,
            self.store.now(),
        )?;
        self.store.reserve_nonce(&proof)?;
        let parts: Vec<&str> = request.path.trim_start_matches('/').split('/').collect();
        match (request.method.as_str(), parts.as_slice()) {
            ("POST", ["v1", "requests"]) => {
                let input: CreateRequest = request.json()?;
                let state = requests::create(
                    &mut self.store,
                    &self.config,
                    &proof,
                    &input,
                    &request.source,
                )?;
                let id = state.request_id.clone();
                let mut response = HttpOutput::json(201, serde_json::to_value(state)?)?;
                response.headers.insert(
                    "Location".into(),
                    format!("{}/v1/requests/{id}/status.md", self.config.public_origin),
                );
                Ok(response)
            }
            ("GET", ["v1", "requests", id]) => {
                let state = requests::state(&mut self.store, &self.config, id, &proof.actor_id)?;
                HttpOutput::json(200, serde_json::to_value(state)?)
            }
            ("GET", ["v1", "requests", id, "status.md"]) => {
                let state = requests::state(&mut self.store, &self.config, id, &proof.actor_id)?;
                Ok(HttpOutput::text(
                    200,
                    "text/markdown; charset=utf-8",
                    &state.markdown()?,
                ))
            }
            ("POST", ["v1", "requests", id, "claim"]) => {
                let _: Empty = request.json()?;
                HttpOutput::json(200, requests::claim(&mut self.store, id, &proof.actor_id)?)
            }
            ("POST", ["v1", "requests", id, "cancel"]) => {
                let _: Empty = request.json()?;
                HttpOutput::json(200, requests::cancel(&mut self.store, id, &proof.actor_id)?)
            }
            ("POST", ["v1", "requests", id, "email"]) => {
                let input: EmailRequest = request.json()?;
                HttpOutput::json(
                    202,
                    mail::invite(
                        &mut self.store,
                        &self.config,
                        &proof,
                        id,
                        &input,
                        &request.source,
                    )?,
                )
            }
            ("GET", ["v1", "session"]) => {
                let value = self
                    .store
                    .atomic(|db, _| requests::session_context(db, &proof))?;
                HttpOutput::json(200, value)
            }
            ("GET", ["v1", "human", "grants"]) => {
                if proof.authorization != "anonymous" {
                    return Err(Error::forbidden());
                }
                let value = self.store.atomic(|db, _| {
                    requests::list_grants(db, &db::registered_human(db, &proof.actor_id)?)
                })?;
                HttpOutput::json(200, value)
            }
            ("POST", ["v1", "human", "grants", id, "revoke"]) => {
                let _: Empty = request.json()?;
                if proof.authorization != "anonymous" {
                    return Err(Error::forbidden());
                }
                let value = self.store.atomic(|db, _| {
                    requests::revoke(db, id, &db::registered_human(db, &proof.actor_id)?)
                })?;
                HttpOutput::json(200, value)
            }
            ("GET", ["v1", "notes", id]) => {
                HttpOutput::json(200, requests::note(&mut self.store, &proof, id, None)?)
            }
            ("PUT", ["v1", "notes", id]) => {
                let input: NoteUpdate = request.json()?;
                HttpOutput::json(
                    200,
                    requests::note(&mut self.store, &proof, id, Some(&input.content))?,
                )
            }
            _ => Err(Error::not_found()),
        }
    }

    fn browser(&mut self, request: &HttpInput) -> Result<HttpOutput> {
        let parts: Vec<&str> = request.path.trim_start_matches('/').split('/').collect();
        let cookie = request.header("cookie");
        let origin = request.header("origin");
        let csrf = request.header("x-hg-csrf");
        match (request.method.as_str(), parts.as_slice()) {
            ("GET", ["human", "grants"]) => HttpOutput::page(
                human::grants_page(
                    &mut self.store,
                    &self.config,
                    self.authenticator.as_ref(),
                    cookie,
                )?,
                None,
            ),
            ("POST", ["human", "grants", id, "revoke"]) => {
                let _: Empty = request.json()?;
                HttpOutput::json(
                    200,
                    human::revoke(
                        &mut self.store,
                        &self.config,
                        self.authenticator.as_ref(),
                        id,
                        &BrowserWrite {
                            link: "",
                            cookie,
                            origin,
                            csrf,
                        },
                    )?,
                )
            }
            ("GET", ["human", link]) => {
                let (page, new_cookie) = human::page(
                    &mut self.store,
                    &self.config,
                    self.authenticator.as_ref(),
                    link,
                    cookie,
                    &request.source,
                )?;
                HttpOutput::page(page, new_cookie)
            }
            ("POST", ["human", link, "begin"]) => {
                let _: Empty = request.json()?;
                HttpOutput::json(
                    200,
                    human::begin(
                        &mut self.store,
                        &self.config,
                        link,
                        cookie,
                        origin,
                        csrf,
                        &request.source,
                    )?,
                )
            }
            ("POST", ["human", link, "verify"]) => {
                let input: Verification = request.json()?;
                let write = BrowserWrite {
                    link,
                    cookie,
                    origin,
                    csrf,
                };
                let (value, cookie) = human::verify(
                    &mut self.store,
                    &self.config,
                    self.authenticator.as_ref(),
                    &write,
                    &input,
                )?;
                let mut response = HttpOutput::json(200, value)?;
                response.headers.insert("Set-Cookie".into(), cookie);
                Ok(response)
            }
            ("POST", ["human", link, "approve"]) => {
                let input: Approval = request.json()?;
                let write = BrowserWrite {
                    link,
                    cookie,
                    origin,
                    csrf,
                };
                HttpOutput::json(
                    200,
                    human::decide(
                        &mut self.store,
                        &self.config,
                        self.authenticator.as_ref(),
                        &write,
                        Some(&input),
                    )?,
                )
            }
            ("POST", ["human", link, "reject"]) => {
                let _: Empty = request.json()?;
                let write = BrowserWrite {
                    link,
                    cookie,
                    origin,
                    csrf,
                };
                HttpOutput::json(
                    200,
                    human::decide(
                        &mut self.store,
                        &self.config,
                        self.authenticator.as_ref(),
                        &write,
                        None,
                    )?,
                )
            }
            ("GET", ["invite", token]) => {
                let (page, new_cookie) = human::invite_page(
                    &mut self.store,
                    &self.config,
                    token,
                    cookie,
                    &request.source,
                )?;
                HttpOutput::page(page, new_cookie)
            }
            ("POST", ["invite", token, action]) if ["reject", "block"].contains(action) => {
                let _: Empty = request.json()?;
                HttpOutput::json(
                    200,
                    human::refuse_mail(
                        &mut self.store,
                        &self.config,
                        token,
                        cookie,
                        origin,
                        csrf,
                        *action == "block",
                    )?,
                )
            }
            _ => Err(Error::not_found()),
        }
    }
}
