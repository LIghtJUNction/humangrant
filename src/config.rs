use crate::error::{Error, Result};
use crate::model::Permission;
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use std::path::PathBuf;
use url::Url;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AccountSeed {
    pub id: String,
    pub public_key: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceSeed {
    pub id: String,
    pub owner_id: String,
    pub content: String,
    pub permissions: Vec<String>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct MailConfig {
    pub mode: String,
    pub spool: PathBuf,
    pub recipient_cooldown_seconds: i64,
    pub recipient_per_hour: i64,
    pub recipient_per_day: i64,
    pub actor_per_hour: i64,
    pub source_per_hour: i64,
    pub service_per_hour: i64,
    pub service_per_day: i64,
}

impl Default for MailConfig {
    fn default() -> Self {
        Self {
            mode: "local".into(), spool: ".state/outbox".into(),
            recipient_cooldown_seconds: 60, recipient_per_hour: 3, recipient_per_day: 5,
            actor_per_hour: 10, source_per_hour: 10, service_per_hour: 100, service_per_day: 500,
        }
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub public_origin: String,
    pub listen: String,
    pub database: PathBuf,
    pub local_development: bool,
    pub request_ttl_seconds: i64,
    pub grant_ttl_seconds: i64,
    pub poll_interval_seconds: i64,
    pub create_actor_per_hour: i64,
    pub create_source_per_hour: i64,
    pub create_service_per_hour: i64,
    pub mail: MailConfig,
    pub client_ids: Vec<String>,
    pub accounts: Vec<AccountSeed>,
    pub resources: Vec<ResourceSeed>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            public_origin: "http://127.0.0.1:8787".into(), listen: "127.0.0.1:8787".into(),
            database: ".state/humangrant.db".into(), local_development: false,
            request_ttl_seconds: 600, grant_ttl_seconds: 3600, poll_interval_seconds: 5,
            create_actor_per_hour: 20, create_source_per_hour: 60, create_service_per_hour: 300,
            mail: MailConfig::default(), client_ids: vec!["example-cli".into(), "example-browser".into()],
            accounts: vec![], resources: vec![],
        }
    }
}

impl Config {
    pub fn load(path: &std::path::Path) -> Result<Self> {
        let config: Self = serde_json::from_slice(&std::fs::read(path)?)?;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<()> {
        let url = Url::parse(&self.public_origin).map_err(|_| Error::invalid())?;
        let listen: SocketAddr = self.listen.parse().map_err(|_| Error::invalid())?;
        // The cleartext reference listener is never exposed on a public interface.
        if !listen.ip().is_loopback() || self.public_origin != url.origin().ascii_serialization() || url.path() != "/" || url.query().is_some()
            || url.fragment().is_some() || !url.username().is_empty() || url.password().is_some()
            || self.public_origin.ends_with('/')
        { return Err(Error::invalid()); }
        let loopback = matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]" | "::1"));
        if url.scheme() != "https" && !(self.local_development && url.scheme() == "http" && loopback) {
            return Err(Error::invalid());
        }
        if !(60..=1800).contains(&self.request_ttl_seconds)
            || !(60..=86400).contains(&self.grant_ttl_seconds)
            || !(1..=60).contains(&self.poll_interval_seconds)
            || !["disabled", "local", "smtp-worker"].contains(&self.mail.mode.as_str())
        { return Err(Error::invalid()); }
        for limit in [self.mail.recipient_cooldown_seconds, self.mail.recipient_per_hour,
            self.mail.recipient_per_day, self.mail.actor_per_hour, self.mail.source_per_hour,
            self.mail.service_per_hour, self.mail.service_per_day, self.create_actor_per_hour,
            self.create_source_per_hour, self.create_service_per_hour]
        { if !(1..=1_000_000).contains(&limit) { return Err(Error::invalid()); } }
        for id in &self.client_ids { validate_id(id)?; }
        for account in &self.accounts {
            validate_id(&account.id)?;
            crate::crypto::public_key(&account.public_key)?;
        }
        for resource in &self.resources {
            validate_id(&resource.id)?;
            validate_id(&resource.owner_id)?;
            if resource.content.len()>16_384 { return Err(Error::invalid()); }
            for action in &resource.permissions {
                Permission { action: action.clone(), resource: resource.id.clone() }.validate()?;
            }
        }
        Ok(())
    }
}

pub fn validate_id(id: &str) -> Result<()> {
    if id.is_empty() || id.len()>64 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b==b'-' || b==b'_') {
        return Err(Error::invalid());
    }
    Ok(())
}
