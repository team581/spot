//! Ethernet settings, applied by the root `spot-network` helper with trial, confirm, and
//! automatic rollback. The vision service talks to it over a Unix socket.

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

pub const SOCKET: &str = "/run/spot-network.sock";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum AddressMode {
    /// DHCP, as from the robot radio.
    Automatic,
    Static,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct NetworkChange {
    pub mode: AddressMode,
    /// IPv4 address on the robot's /24, for example `10.5.81.12`. Static mode only.
    #[serde(default)]
    pub address: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct NetworkStatus {
    pub mode: AddressMode,
    /// The configured static address, when static.
    pub address: String,
    /// Addresses currently on the Ethernet bridge.
    pub addresses: Vec<String>,
    /// The fixed maintenance address that is always present.
    pub maintenance_address: String,
    /// Whether an Ethernet cable has link.
    pub connected: bool,
    /// A change waiting to be confirmed before it rolls back.
    pub pending: Option<PendingChange>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct PendingChange {
    pub mode: AddressMode,
    pub address: String,
    /// Seconds until the change rolls back on its own.
    pub remaining_s: u64,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "operation", content = "payload", rename_all = "snake_case")]
pub enum Request {
    Status,
    Apply(NetworkChange),
    Confirm,
    Revert,
}

pub type Reply = Result<NetworkStatus, String>;

/// Sends one request to the helper.
pub async fn request(request: &Request) -> Reply {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    let exchange = async {
        let mut stream = tokio::net::UnixStream::connect(SOCKET).await?;
        let mut line = serde_json::to_vec(request)?;
        line.push(b'\n');
        stream.write_all(&line).await?;
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).await?;
        anyhow::Ok(serde_json::from_str::<Reply>(&reply)?)
    };
    match tokio::time::timeout(std::time::Duration::from_secs(60), exchange).await {
        Ok(Ok(reply)) => reply,
        Ok(Err(error)) => Err(format!("Network helper unavailable: {error}")),
        Err(_) => Err("Network helper did not respond".into()),
    }
}
