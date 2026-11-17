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
    pub client_ids: Vec<String>,
    pub accounts: Vec<AccountSeed>,
    pub resources: Vec<ResourceSeed>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            public_origin: "http://127.0.0.1:8787".into(),
            listen: "127.0.0.1:8787".into(),
            database: ".state/humangrant.db".into(),
            local_development: false,
            request_ttl_seconds: 600,
            grant_ttl_seconds: 3600,
            poll_interval_seconds: 5,
            create_actor_per_hour: 20,
            create_source_per_hour: 60,
            create_service_per_hour: 300,
            client_ids: vec!["example-cli".into()],
            accounts: vec![],
            resources: vec![],
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
        if !listen.ip().is_loopback()
            || self.public_origin != url.origin().ascii_serialization()
            || url.path() != "/"
            || url.query().is_some()
            || url.fragment().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
            || self.public_origin.ends_with('/')
        {
            return Err(Error::invalid());
        }
        let loopback = matches!(
            url.host_str(),
            Some("localhost" | "127.0.0.1" | "[::1]" | "::1")
        );
        if url.scheme() != "https"
            && !(self.local_development && url.scheme() == "http" && loopback)
        {
            return Err(Error::invalid());
        }
        if !(60..=1800).contains(&self.request_ttl_seconds)
            || !(60..=86400).contains(&self.grant_ttl_seconds)
            || !(1..=60).contains(&self.poll_interval_seconds)
        {
            return Err(Error::invalid());
        }
        for limit in [
            self.create_actor_per_hour,
            self.create_source_per_hour,
            self.create_service_per_hour,
        ] {
            if !(1..=1_000_000).contains(&limit) {
                return Err(Error::invalid());
            }
        }
        for id in &self.client_ids {
            validate_id(id)?;
        }
        for account in &self.accounts {
            validate_id(&account.id)?;
            crate::crypto::public_key(&account.public_key)?;
        }
        for resource in &self.resources {
            validate_id(&resource.id)?;
            validate_id(&resource.owner_id)?;
            if resource.content.len() > 16_384 {
                return Err(Error::invalid());
            }
            for action in &resource.permissions {
                Permission {
                    action: action.clone(),
                    resource: resource.id.clone(),
                }
                .validate()?;
            }
        }
        Ok(())
    }
}

pub fn validate_id(id: &str) -> Result<()> {
    if id.is_empty()
        || id.len() > 64
        || !id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err(Error::invalid());
    }
    Ok(())
}
