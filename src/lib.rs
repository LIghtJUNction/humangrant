//! HumanGrant reference server. See `spec/v0.1.md` for wire contracts and security boundaries.
pub mod auth;
pub mod config;
pub mod crypto;
pub mod db;
pub mod error;
pub mod human;
pub mod mail;
pub mod model;
pub mod requests;
pub mod web;

pub use web::{App, HttpInput, HttpOutput};
