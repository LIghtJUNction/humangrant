use crate::crypto::{key_id, verify_detached};
use crate::error::{Error, Result};
use rusqlite::{Connection, OptionalExtension};

pub struct HumanPrincipal { pub account_id: String }

/// A trusted, in-process integration boundary. Implementations must verify real account evidence.
/// This is not an HTTP endpoint that accepts arbitrary account IDs.
pub trait HumanAuthenticator: Send + Sync {
    fn authenticate(&self, db: &Connection, public_key: &str, challenge: &str,
        signature: &str) -> Result<HumanPrincipal>;
}

pub struct PublicKeyAuthenticator;

impl HumanAuthenticator for PublicKeyAuthenticator {
    fn authenticate(&self, db: &Connection, public_key: &str, challenge: &str,
        signature: &str) -> Result<HumanPrincipal>
    {
        verify_detached(public_key,challenge.as_bytes(),signature)?;
        let id=key_id(public_key)?;
        let account=db.query_row("SELECT id FROM accounts WHERE key_id=?1 AND public_key=?2 AND enabled=1",
            rusqlite::params![id,public_key],|r| r.get::<_,String>(0)).optional()?;
        Ok(HumanPrincipal { account_id: account.ok_or_else(Error::forbidden)? })
    }
}
