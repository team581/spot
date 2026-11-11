//! Root helper that changes Spot's Ethernet addressing through NetworkManager.
//!
//! A change starts as an in-memory trial connection guarded by a NetworkManager checkpoint,
//! which rolls back on its own unless the operator confirms in time. Runs from
//! `spot-network.socket` and serves one JSON request per connection.

#[path = "../network.rs"]
#[allow(dead_code)]
mod network;

use std::net::Ipv4Addr;
use std::time::{Duration, Instant};

use network::{AddressMode, NetworkChange, NetworkStatus, PendingChange, Reply, Request};
use serde::Deserialize;
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;

const NM: &str = "org.freedesktop.NetworkManager";
const NM_PATH: &str = "/org/freedesktop/NetworkManager";
const SAVED: &str = "Spot Ethernet override";
const TRIAL: &str = "Spot Ethernet trial";
const ROLLBACK_S: u64 = 90;

#[derive(Deserialize)]
struct Settings {
    interface: String,
    maintenance_address: String,
    default_connection: String,
}

struct Pending {
    change: NetworkChange,
    connection: String,
    previous: String,
    checkpoint: String,
    deadline: Instant,
}

struct Helper {
    settings: Settings,
    pending: Option<Pending>,
}

struct Link {
    connection: String,
    connected: bool,
    addresses: Vec<String>,
    mode: AddressMode,
    address: String,
}

async fn run(program: &str, args: &[&str], timeout: u64) -> Result<String, String> {
    let output = tokio::time::timeout(
        Duration::from_secs(timeout),
        Command::new(program).args(args).env("LC_ALL", "C").output(),
    )
    .await
    .map_err(|_| "Network service did not respond; a pending change still rolls back".to_string())?
    .map_err(|e| format!("{program}: {e}"))?;
    if !output.status.success() {
        let error = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if error.is_empty() { format!("{program} failed") } else { error });
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

async fn nm(args: &[&str]) -> Result<String, String> {
    run("nmcli", args, 8).await
}

async fn bus(method: &str, signature: &str, args: &[&str]) -> Result<Value, String> {
    let mut all = vec!["--system", "--json=short", "call", NM, NM_PATH, NM, method, signature];
    all.extend_from_slice(args);
    let reply = run("busctl", &all, 8).await?;
    if reply.is_empty() {
        return Ok(Value::Null);
    }
    let value: Value = serde_json::from_str(&reply).map_err(|e| e.to_string())?;
    Ok(value["data"].clone())
}

async fn checkpoints() -> Result<Vec<String>, String> {
    let args = ["--system", "--json=short", "get-property", NM, NM_PATH, NM, "Checkpoints"];
    let value: Value =
        serde_json::from_str(&run("busctl", &args, 8).await?).map_err(|e| e.to_string())?;
    Ok(value["data"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_str().map(String::from))
        .collect())
}

/// Parses `a.b.c.d[/prefix]` (default /24, as on FRC robot networks) into a usable host address.
fn parse_address(input: &str) -> Result<(Ipv4Addr, u8), String> {
    let error = || "Use an IPv4 address, for example 10.5.81.11 or 10.5.81.11/24".to_string();
    let (ip, prefix) = input.split_once('/').unwrap_or((input, "24"));
    let ip: Ipv4Addr = ip.trim().parse().map_err(|_| error())?;
    let prefix: u8 = prefix.trim().parse().map_err(|_| error())?;
    let mask = if prefix == 0 { 0 } else { u32::MAX << (32 - prefix.min(32)) };
    let bits = u32::from(ip);
    let usable = (1..=30).contains(&prefix)
        && !(ip.is_multicast() || ip.is_loopback() || ip.is_link_local() || ip.is_unspecified())
        && ip.octets()[0] < 240
        && bits & !mask != 0
        && bits & !mask != !mask;
    if !usable {
        return Err("Choose a usable IPv4 host address and prefix /1 through /30".into());
    }
    Ok((ip, prefix))
}

fn overlaps(a: (Ipv4Addr, u8), b: (Ipv4Addr, u8)) -> bool {
    let prefix = a.1.min(b.1);
    let mask = if prefix == 0 { 0 } else { u32::MAX << (32 - prefix) };
    u32::from(a.0) & mask == u32::from(b.0) & mask
}

impl Helper {
    async fn link(&self) -> Result<Link, String> {
        let interface = &self.settings.interface;
        let links: Value =
            serde_json::from_str(&run("ip", &["-json", "address", "show"], 8).await?)
                .map_err(|e| e.to_string())?;
        let link = links
            .as_array()
            .into_iter()
            .flatten()
            .find(|l| l["ifname"] == interface.as_str())
            .ok_or("The Spot Ethernet bridge is unavailable")?;
        let connection = nm(&["-g", "GENERAL.CON-UUID", "device", "show", interface]).await?;
        if connection.is_empty() || connection == "--" {
            return Err("The Spot Ethernet bridge has no active connection".into());
        }
        let method = nm(&["-g", "ipv4.method", "connection", "show", "uuid", &connection]).await?;
        let configured =
            nm(&["-g", "ipv4.addresses", "connection", "show", "uuid", &connection]).await?;
        let mode = if method == "manual" { AddressMode::Static } else { AddressMode::Automatic };
        Ok(Link {
            connected: link["flags"].as_array().into_iter().flatten().any(|f| f == "LOWER_UP"),
            addresses: inet(link),
            address: match mode {
                AddressMode::Static => configured
                    .split(',')
                    .map(str::trim)
                    .find(|a| !a.is_empty() && *a != self.settings.maintenance_address)
                    .unwrap_or_default()
                    .to_string(),
                AddressMode::Automatic => String::new(),
            },
            connection,
            mode,
        })
    }

    async fn connections(&self) -> Result<Vec<(String, String)>, String> {
        let rows = nm(&["-t", "-f", "UUID,NAME", "connection", "show"]).await?;
        Ok(rows
            .lines()
            .filter_map(|row| row.split_once(':'))
            .map(|(uuid, name)| (uuid.to_string(), name.to_string()))
            .collect())
    }

    /// Deletes a connection only if Spot created it.
    async fn delete_owned(&self, uuid: &str) -> Result<(), String> {
        let owned = self
            .connections()
            .await?
            .iter()
            .any(|(u, name)| u == uuid && (name == SAVED || name == TRIAL));
        if owned && uuid != self.settings.default_connection {
            nm(&["connection", "delete", "uuid", uuid]).await?;
        }
        Ok(())
    }

    async fn rollback(&self, checkpoint: &str) -> Result<(), String> {
        if checkpoints().await?.iter().any(|c| c == checkpoint) {
            bus("CheckpointRollback", "o", &[checkpoint]).await?;
        }
        Ok(())
    }

    /// Forgets a trial whose checkpoint already rolled back.
    async fn expire(&mut self) -> Result<(), String> {
        if let Some(pending) = &self.pending
            && !checkpoints().await?.contains(&pending.checkpoint)
        {
            let connection = pending.connection.clone();
            self.pending = None;
            self.delete_owned(&connection).await?;
        }
        Ok(())
    }

    async fn status(&mut self) -> Reply {
        self.expire().await?;
        let link = self.link().await?;
        Ok(NetworkStatus {
            mode: link.mode,
            address: link.address,
            addresses: link.addresses,
            maintenance_address: self.settings.maintenance_address.clone(),
            connected: link.connected,
            pending: self.pending.as_ref().map(|p| PendingChange {
                mode: p.change.mode,
                address: p.change.address.clone(),
                remaining_s: p.deadline.saturating_duration_since(Instant::now()).as_secs(),
            }),
        })
    }

    async fn apply(&mut self, mut change: NetworkChange) -> Reply {
        self.expire().await?;
        if self.pending.is_some() {
            return Err("Confirm or revert the pending network change first".into());
        }
        let maintenance = self.settings.maintenance_address.clone();
        let link = self.link().await?;
        let connections = self.connections().await?;
        let previous = link.connection.clone();
        let saved = connections.iter().any(|(u, name)| *u == previous && name == SAVED);
        if previous != self.settings.default_connection && !saved {
            return Err("The active bridge connection is not managed by Spot".into());
        }
        if !link.addresses.contains(&maintenance) {
            return Err("Restore the maintenance address before changing settings".into());
        }
        match change.mode {
            AddressMode::Automatic => change.address.clear(),
            AddressMode::Static => {
                let address = parse_address(&change.address)?;
                if parse_address(&maintenance).is_ok_and(|m| m.0 == address.0) {
                    return Err("The maintenance address is fixed".into());
                }
                let links: Value =
                    serde_json::from_str(&run("ip", &["-json", "address", "show"], 8).await?)
                        .map_err(|e| e.to_string())?;
                for other in links.as_array().into_iter().flatten() {
                    if other["ifname"] == self.settings.interface.as_str() {
                        continue;
                    }
                    if inet(other)
                        .iter()
                        .filter_map(|a| parse_address(a).ok())
                        .any(|a| overlaps(a, address))
                    {
                        return Err("This subnet overlaps another Jetson network".into());
                    }
                }
                change.address = format!("{}/{}", address.0, address.1);
            }
        }
        for (uuid, name) in &connections {
            if name == TRIAL {
                self.delete_owned(uuid).await?;
            }
        }
        // Clone the Nix-owned template, including its bridge policy. The trial stays in
        // memory until it is confirmed.
        nm(&[
            "connection",
            "clone",
            "--temporary",
            "uuid",
            &self.settings.default_connection,
            TRIAL,
        ])
        .await?;
        let connection = nm(&["-g", "connection.uuid", "connection", "show", TRIAL]).await?;
        let result = async {
            let mut addresses = maintenance.clone();
            if change.mode == AddressMode::Static {
                addresses = format!("{addresses},{}", change.address);
            }
            let method = if change.mode == AddressMode::Static { "manual" } else { "auto" };
            nm(&[
                "connection",
                "modify",
                "--temporary",
                "uuid",
                &connection,
                "connection.autoconnect",
                "no",
                "connection.autoconnect-priority",
                "100",
                "ipv4.method",
                method,
                "ipv4.addresses",
                &addresses,
            ])
            .await?;
            let device =
                nm(&["-g", "GENERAL.DBUS-PATH", "device", "show", &self.settings.interface])
                    .await?;
            let deadline = Instant::now() + Duration::from_secs(ROLLBACK_S);
            let timeout = ROLLBACK_S.to_string();
            let checkpoint =
                bus("CheckpointCreate", "aouu", &["1", &device, &timeout, "0"]).await?;
            let checkpoint =
                checkpoint[0].as_str().ok_or("NetworkManager returned no checkpoint")?.to_string();
            self.pending = Some(Pending {
                change: change.clone(),
                connection: connection.clone(),
                previous: previous.clone(),
                checkpoint: checkpoint.clone(),
                deadline,
            });
            run("nmcli", &["--wait", "45", "connection", "up", "uuid", &connection], 49).await?;
            Ok::<_, String>(())
        }
        .await;
        if let Err(error) = result {
            if let Some(pending) = self.pending.take() {
                let _ = self.rollback(&pending.checkpoint).await;
            }
            let _ = self.delete_owned(&connection).await;
            return Err(error);
        }
        self.status().await
    }

    async fn confirm(&mut self) -> Reply {
        self.expire().await?;
        let pending =
            self.pending.as_ref().ok_or("This network change expired or was already reverted")?;
        let link = self.link().await?;
        let ready = match pending.change.mode {
            AddressMode::Static => link.addresses.contains(&pending.change.address),
            AddressMode::Automatic => {
                link.addresses.iter().any(|a| *a != self.settings.maintenance_address)
            }
        };
        if link.connection != pending.connection
            || !link.connected
            || !link.addresses.contains(&self.settings.maintenance_address)
            || !ready
        {
            return Err("Wait for both the maintenance and robot addresses, or revert".into());
        }
        nm(&[
            "connection",
            "modify",
            "uuid",
            &pending.connection,
            "connection.id",
            SAVED,
            "connection.autoconnect",
            "yes",
        ])
        .await?;
        bus("CheckpointDestroy", "o", &[&pending.checkpoint]).await?;
        let previous = pending.previous.clone();
        self.pending = None;
        self.delete_owned(&previous).await?;
        self.status().await
    }

    async fn revert(&mut self) -> Reply {
        if let Some(pending) = self.pending.take() {
            self.rollback(&pending.checkpoint).await?;
            self.delete_owned(&pending.connection).await?;
        }
        self.status().await
    }

    async fn handle(&mut self, request: Request) -> Reply {
        match request {
            Request::Status => self.status().await,
            Request::Apply(change) => self.apply(change).await,
            Request::Confirm => self.confirm().await,
            Request::Revert => self.revert().await,
        }
    }
}

fn inet(link: &Value) -> Vec<String> {
    link["addr_info"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|a| a["family"] == "inet")
        .filter_map(|a| Some(format!("{}/{}", a["local"].as_str()?, a["prefixlen"].as_u64()?)))
        .collect()
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    use std::os::fd::FromRawFd;
    anyhow::ensure!(
        std::env::var("LISTEN_FDS").as_deref() == Ok("1"),
        "run through spot-network.socket"
    );
    let settings: Settings =
        serde_json::from_str(&std::fs::read_to_string("/etc/spot-vision/network.json")?)?;
    // SAFETY: systemd passes the listening socket as fd 3.
    let listener = unsafe { std::os::unix::net::UnixListener::from_raw_fd(3) };
    listener.set_nonblocking(true)?;
    let listener = tokio::net::UnixListener::from_std(listener)?;
    let mut helper = Helper { settings, pending: None };
    // A trial left by a previous run has no checkpoint to confirm against.
    for (uuid, name) in helper.connections().await.unwrap_or_default() {
        if name == TRIAL {
            let _ = helper.delete_owned(&uuid).await;
        }
    }
    loop {
        let (stream, _) = listener.accept().await?;
        let (read, mut write) = stream.into_split();
        let mut line = String::new();
        let reply = match tokio::time::timeout(
            Duration::from_secs(5),
            BufReader::new(read).read_line(&mut line),
        )
        .await
        {
            Ok(Ok(_)) => match serde_json::from_str::<Request>(&line) {
                Ok(request) => helper.handle(request).await,
                Err(error) => Err(format!("Invalid network request: {error}")),
            },
            _ => Err("Network request timed out".into()),
        };
        let mut bytes = serde_json::to_vec(&reply)?;
        bytes.push(b'\n');
        let _ = write.write_all(&bytes).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_robot_addresses() {
        assert_eq!(parse_address("10.5.81.11"), Ok(("10.5.81.11".parse().unwrap(), 24)));
        assert_eq!(parse_address("10.5.81.11/16"), Ok(("10.5.81.11".parse().unwrap(), 16)));
        assert!(parse_address("10.5.81.0").is_err());
        assert!(parse_address("10.5.81.255").is_err());
        assert!(parse_address("127.0.0.1").is_err());
        assert!(parse_address("10.5.81.11/31").is_err());
    }
}
