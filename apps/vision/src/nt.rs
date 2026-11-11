//! Minimal NetworkTables 4 client: time sync, publishing, and prefix subscriptions.

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::Context;
use futures_util::{SinkExt, StreamExt};
use rmpv::Value;
use serde_json::json;
use tokio::sync::{mpsc, watch};
use tokio::time::{Instant, MissedTickBehavior, interval, sleep, timeout};
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;

use crate::clock::monotonic_us;
use crate::structs::SCHEMAS;

const NAME: &str = "spot";
const SUBSCRIPTIONS: &[&str] = &["/Spot/inputs/", "/FMSInfo/"];
/// Time sync samples kept; the lowest round trip wins.
const SYNC_SAMPLES: usize = 8;

pub enum NtValue {
    String(String),
    Raw(Vec<u8>),
}

impl NtValue {
    fn type_id(&self) -> i64 {
        match self {
            NtValue::String(_) => 4,
            NtValue::Raw(_) => 5,
        }
    }
    fn into_msgpack(self) -> Value {
        match self {
            NtValue::String(v) => Value::from(v),
            NtValue::Raw(v) => Value::Binary(v),
        }
    }
}

struct Outgoing {
    topic: String,
    type_name: String,
    value: NtValue,
    server_time_us: i64,
}

/// Receives subscribed values and connection changes.
pub trait Handler: Send + Sync + 'static {
    fn value(&self, topic: &str, value: Value);
    fn connection_changed(&self);
}

pub struct Nt {
    out: mpsc::Sender<Outgoing>,
    offset_us: AtomicI64,
    synced: AtomicBool,
    server: Mutex<Option<String>>,
}

impl Nt {
    /// Starts the client. `servers` holds the hosts to try, in order.
    pub fn spawn(servers: watch::Receiver<Vec<String>>, handler: Arc<dyn Handler>) -> Arc<Nt> {
        let (out, rx) = mpsc::channel(4096);
        let nt = Arc::new(Nt {
            out,
            offset_us: AtomicI64::new(0),
            synced: AtomicBool::new(false),
            server: Mutex::new(None),
        });
        tokio::spawn(run(nt.clone(), rx, servers, handler));
        nt
    }

    pub fn server(&self) -> Option<String> {
        self.server.lock().unwrap().clone()
    }

    pub fn synced(&self) -> bool {
        self.synced.load(Ordering::Relaxed)
    }

    /// Converts a local monotonic time to NT server time, once time sync is acquired.
    pub fn server_time_us(&self, monotonic_us: i64) -> Option<i64> {
        self.synced().then(|| monotonic_us + self.offset_us.load(Ordering::Relaxed))
    }

    /// Queues a value stamped with a local monotonic time. Values are dropped until time
    /// sync is acquired or if the connection cannot keep up; this never blocks.
    pub fn publish(&self, topic: &str, type_name: &str, value: NtValue, monotonic_us: i64) {
        let Some(server_time_us) = self.server_time_us(monotonic_us) else { return };
        let _ = self.out.try_send(Outgoing {
            topic: topic.to_string(),
            type_name: type_name.to_string(),
            value,
            server_time_us,
        });
    }
}

async fn run(
    nt: Arc<Nt>,
    mut rx: mpsc::Receiver<Outgoing>,
    mut servers: watch::Receiver<Vec<String>>,
    handler: Arc<dyn Handler>,
) {
    // Publishers survive reconnects so they can be announced again.
    let mut publishers: HashMap<String, (i64, String)> = HashMap::new();
    loop {
        let candidates = servers.borrow_and_update().clone();
        for host in &candidates {
            let address = if host.contains(':') { host.clone() } else { format!("{host}:5810") };
            let Ok(Ok(socket)) = timeout(Duration::from_secs(2), connect(&address)).await else {
                continue;
            };
            tracing::info!(server = %address, "NetworkTables connected");
            *nt.server.lock().unwrap() = Some(address.clone());
            handler.connection_changed();
            let result =
                session(socket, &nt, &mut rx, &mut servers, &*handler, &mut publishers).await;
            nt.synced.store(false, Ordering::Relaxed);
            *nt.server.lock().unwrap() = None;
            handler.connection_changed();
            tracing::info!(server = %address, reason = ?result.err(), "NetworkTables disconnected");
            break;
        }
        tokio::select! {
            _ = sleep(Duration::from_millis(500)) => {}
            _ = servers.changed() => {}
        }
        // Drop values queued while disconnected rather than sending stale data.
        while rx.try_recv().is_ok() {}
    }
}

type Socket =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn connect(address: &str) -> anyhow::Result<Socket> {
    let mut request = format!("ws://{address}/nt/{NAME}").into_client_request()?;
    request.headers_mut().insert(
        "Sec-WebSocket-Protocol",
        "v4.1.networktables.first.wpi.edu, networktables.first.wpi.edu".parse()?,
    );
    Ok(tokio_tungstenite::connect_async(request).await?.0)
}

async fn session(
    socket: Socket,
    nt: &Nt,
    rx: &mut mpsc::Receiver<Outgoing>,
    servers: &mut watch::Receiver<Vec<String>>,
    handler: &dyn Handler,
    publishers: &mut HashMap<String, (i64, String)>,
) -> anyhow::Result<()> {
    let (mut sink, mut stream) = socket.split();
    let mut messages = vec![json!({
        "method": "subscribe",
        "params": { "topics": SUBSCRIPTIONS, "subuid": 1, "options": { "prefix": true } },
    })];
    for (topic, (pubuid, type_name)) in publishers.iter() {
        messages.push(publish_message(topic, *pubuid, type_name));
    }
    sink.send(Message::Text(serde_json::to_string(&messages)?.into())).await?;
    for (name, schema) in SCHEMAS {
        let topic = format!("/.schema/struct:{name}");
        let pubuid = ensure_publisher(&mut sink, publishers, &topic, "structschema").await?;
        let value = NtValue::Raw(schema.as_bytes().to_vec());
        sink.send(binary(pubuid, 0, value)?).await?;
    }

    let mut topics: HashMap<i64, String> = HashMap::new();
    let mut samples: VecDeque<(i64, i64)> = VecDeque::new();
    let mut sync = interval(Duration::from_secs(1));
    sync.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let mut last_heard = Instant::now();
    loop {
        tokio::select! {
            _ = sync.tick() => {
                if last_heard.elapsed() > Duration::from_secs(3) {
                    anyhow::bail!("server stopped responding");
                }
                let request = Value::Array(vec![
                    Value::from(-1), Value::from(0), Value::from(2), Value::from(monotonic_us()),
                ]);
                let mut bytes = Vec::new();
                rmpv::encode::write_value(&mut bytes, &request)?;
                sink.send(Message::Binary(bytes.into())).await?;
            }
            message = stream.next() => {
                let message = message.context("closed")??;
                last_heard = Instant::now();
                match message {
                    Message::Text(text) => {
                        let Ok(messages) = serde_json::from_str::<Vec<serde_json::Value>>(&text) else {
                            continue;
                        };
                        for message in messages {
                            let params = &message["params"];
                            match message["method"].as_str() {
                                Some("announce") => {
                                    if let (Some(id), Some(name)) = (params["id"].as_i64(), params["name"].as_str()) {
                                        topics.insert(id, name.to_string());
                                    }
                                }
                                Some("unannounce") => {
                                    if let Some(id) = params["id"].as_i64() {
                                        topics.remove(&id);
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    Message::Binary(bytes) => {
                        let mut cursor = &bytes[..];
                        while !cursor.is_empty() {
                            let value = rmpv::decode::read_value(&mut cursor)?;
                            let Value::Array(mut parts) = value else { continue };
                            if parts.len() != 4 {
                                continue;
                            }
                            let data = parts.pop().unwrap();
                            let (Some(id), Some(time)) = (parts[0].as_i64(), parts[1].as_i64()) else {
                                continue;
                            };
                            if id == -1 {
                                let Some(sent) = data.as_i64() else { continue };
                                let now = monotonic_us();
                                let rtt = now - sent;
                                samples.push_back((rtt, time + rtt / 2 - now));
                                if samples.len() > SYNC_SAMPLES {
                                    samples.pop_front();
                                }
                                let (_, offset) = *samples.iter().min().unwrap();
                                nt.offset_us.store(offset, Ordering::Relaxed);
                                nt.synced.store(true, Ordering::Relaxed);
                            } else if let Some(topic) = topics.get(&id) {
                                handler.value(topic, data);
                            }
                        }
                    }
                    Message::Close(_) => anyhow::bail!("closed by server"),
                    _ => {}
                }
            }
            outgoing = rx.recv() => {
                let Some(outgoing) = outgoing else { return Ok(()) };
                let pubuid =
                    ensure_publisher(&mut sink, publishers, &outgoing.topic, &outgoing.type_name).await?;
                sink.send(binary(pubuid, outgoing.server_time_us, outgoing.value)?).await?;
            }
            _ = servers.changed() => return Ok(()),
        }
    }
}

fn publish_message(topic: &str, pubuid: i64, type_name: &str) -> serde_json::Value {
    json!({
        "method": "publish",
        "params": { "name": topic, "pubuid": pubuid, "type": type_name, "properties": {} },
    })
}

async fn ensure_publisher(
    sink: &mut futures_util::stream::SplitSink<Socket, Message>,
    publishers: &mut HashMap<String, (i64, String)>,
    topic: &str,
    type_name: &str,
) -> anyhow::Result<i64> {
    if let Some((pubuid, _)) = publishers.get(topic) {
        return Ok(*pubuid);
    }
    let pubuid = publishers.len() as i64 + 1;
    publishers.insert(topic.to_string(), (pubuid, type_name.to_string()));
    let message = serde_json::to_string(&[publish_message(topic, pubuid, type_name)])?;
    sink.send(Message::Text(message.into())).await?;
    Ok(pubuid)
}

fn binary(pubuid: i64, time_us: i64, value: NtValue) -> anyhow::Result<Message> {
    let frame = Value::Array(vec![
        Value::from(pubuid),
        Value::from(time_us),
        Value::from(value.type_id()),
        value.into_msgpack(),
    ]);
    let mut bytes = Vec::new();
    rmpv::encode::write_value(&mut bytes, &frame)?;
    Ok(Message::Binary(bytes.into()))
}
