use serde::Serialize;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, Serialize)]
pub struct Error {
    #[serde(skip)]
    pub status: u16,
    pub error: &'static str,
    pub message: &'static str,
    pub retry_after_seconds: u64,
}

impl Error {
    pub fn new(status: u16, error: &'static str, message: &'static str) -> Self {
        Self {
            status,
            error,
            message,
            retry_after_seconds: 0,
        }
    }

    pub fn invalid() -> Self {
        Self::new(
            400,
            "invalid_request",
            "The request is not valid for this protocol version.",
        )
    }

    pub fn forbidden() -> Self {
        Self::new(
            403,
            "forbidden",
            "This identity does not have permission for this operation.",
        )
    }

    pub fn state() -> Self {
        Self::new(
            409,
            "invalid_state",
            "This operation is not allowed in the current state.",
        )
    }

    pub fn not_found() -> Self {
        Self::new(
            404,
            "not_found",
            "The requested object is not available to this identity.",
        )
    }

    pub fn slow_down(seconds: u64) -> Self {
        Self {
            status: 429,
            error: "slow_down",
            message: "Wait before reading the state again.",
            retry_after_seconds: seconds,
        }
    }

    pub fn internal() -> Self {
        Self::new(
            500,
            "internal_error",
            "The server could not complete the operation.",
        )
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.error)
    }
}
impl std::error::Error for Error {}
impl From<rusqlite::Error> for Error {
    fn from(_: rusqlite::Error) -> Self {
        Self::internal()
    }
}
impl From<std::io::Error> for Error {
    fn from(_: std::io::Error) -> Self {
        Self::internal()
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::invalid()
    }
}
