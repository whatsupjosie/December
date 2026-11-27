/*!
PubCast WebSocket Renderer Server
===================================

This is the receiving end of the live mocap pipeline.

Data flow:
  Python MocapPrecisionCapture
    → avatar_performer.py (retarget + blend)
      → PerformerStreamer (WebSocket client)
        → THIS SERVER (tokio-tungstenite)
          → SkeletalAnimator::apply_motion_capture_frame()
            → recompute world matrices
              → RenderTick (world matrices + blendshapes)
                → render subscribers (WebSocket) and/or stdout callback

Architecture:
  - One `tokio::task` per WebSocket connection
  - One `SkeletalAnimator` per `avatar_id` stored in `AvatarRegistry`
  - AvatarRegistry is `Arc<RwLock<...>>` so tasks share it safely
  - Render tick at configurable FPS (default 60) reads world matrices from
    all registered animators and publishes them on a broadcast channel
  - Graceful shutdown on Ctrl+C everywhere, plus SIGTERM on Unix and
    Ctrl+Break on Windows, via a broadcast shutdown channel

Connection protocol (one socket can do either or both):
  Performer (avatar_performer.py — unchanged):
    - Sends JSON text frames matching `BridgeMotionPayload` (lib.rs)
    - Server acks each frame with
        {"ok": true, "frame": N, "avatar_id": "...", "latency_us": N}
    - On rejection (bad JSON, server full) the ack is
        {"ok": false, "error": "...", "avatar_id": "..." | null}
  Render subscriber (voxel bridge client, browser renderer, recorder...):
    - Sends {"subscribe": "render"} once
    - Server replies {"ok": true, "subscribed": "render"} followed at once by a
      full snapshot tick, then `render_tick` frames:
        {"type": "render_tick", "tick": N, "timestamp": f64, "full": bool,
         "avatars": [RenderedAvatar...], "evicted": ["avatar_id"...]}
      world_matrices are flat f32 arrays, 16 values per joint (column-major).
    - When `always_emit` is off (default), a tick carries only avatars whose
      pose changed since the previous tick; ticks with no change and no
      eviction are not sent. A subscriber keeps the last pose it was given.
    - Sends {"unsubscribe": "render"} to stop.

Render callback (PUBCAST_RENDER_CALLBACK):
  none         (default) only WebSocket subscribers receive ticks
  stdout       also print every emitted tick as one JSON line on stdout
               (logs go to stderr, so stdout stays clean for piping)
  voxel_bridge NOT built into this binary. The server says so at startup and
               runs as `none`. Connect the voxel bridge as a render subscriber.

Configuration — command-line flags override environment variables:
  --port N         PUBCAST_WS_PORT          default 8765
  --bind ADDR      PUBCAST_WS_BIND          default 127.0.0.1 (this machine only;
                                            0.0.0.0 opens it to the network)
  --fps N          PUBCAST_RENDER_FPS       default 60   (1–240)
  --max-avatars N  PUBCAST_MAX_AVATARS      default 16   (1–64)
  --ttl SECONDS    PUBCAST_AVATAR_TTL_SEC   default 30   (0–3600)
  --always-emit    PUBCAST_ALWAYS_EMIT=1    default off
  --callback NAME  PUBCAST_RENDER_CALLBACK  default none
  --log-level LVL  RUST_LOG                 default info for this server and
                                            pubcast_animation
  --help

Cargo dependencies used:
  tokio          = { version = "1", features = ["full"] }
  tokio-tungstenite = "0.23"
  futures-util   = "0.3"
  serde, serde_json, anyhow, tracing
  tracing-subscriber = { version = "0.3", features = ["env-filter"] }

Usage:
  cargo run --bin ws_renderer
  cargo run --bin ws_renderer -- --port 8765 --fps 60 --log-level debug
*/

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{broadcast, RwLock};
use tokio::time;
use tokio_tungstenite::{accept_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

// Re-use types from the animation crate
use pubcast_animation::{BridgeMotionPayload, SkeletalAnimator, SkeletonHierarchy};

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_PORT: u16 = 8765;
const DEFAULT_LOG_FILTER: &str = "ws_renderer=info,pubcast_animation=info";

/// Where emitted render ticks go besides WebSocket subscribers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RenderCallback {
    /// Only WebSocket render subscribers.
    None,
    /// Also one JSON line per emitted tick on stdout.
    Stdout,
}

#[derive(Debug, Clone)]
pub struct RendererConfig {
    /// WebSocket listen address
    pub listen_addr:     SocketAddr,
    /// Target render tick rate (Hz). Separate from mocap frame rate.
    pub render_fps:      u32,
    /// Maximum number of simultaneous avatars
    pub max_avatars:     usize,
    /// How long to keep an avatar alive after last motion update before eviction
    pub avatar_ttl_sec:  u64,
    /// Emit every avatar on every render tick (true),
    /// or only avatars whose pose changed (false, more efficient)
    pub always_emit:     bool,
    /// Extra destination for emitted ticks
    pub render_callback: RenderCallback,
}

impl Default for RendererConfig {
    fn default() -> Self {
        Self {
            listen_addr:     SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), DEFAULT_PORT),
            render_fps:      60,
            max_avatars:     16,
            avatar_ttl_sec:  30,
            always_emit:     false,
            render_callback: RenderCallback::None,
        }
    }
}

/// Raw settings gathered from flags and environment before they are combined.
/// Every field is optional so flags can override only what they name.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct Settings {
    pub port:        Option<String>,
    pub bind:        Option<String>,
    pub fps:         Option<String>,
    pub max_avatars: Option<String>,
    pub ttl:         Option<String>,
    pub always_emit: Option<String>,
    pub callback:    Option<String>,
    pub log_level:   Option<String>,
    pub help:        bool,
}

impl Settings {
    /// Read the PUBCAST_* environment variables (and RUST_LOG).
    pub fn from_env() -> Self {
        let get = |k: &str| std::env::var(k).ok().filter(|v| !v.trim().is_empty());
        Self {
            port:        get("PUBCAST_WS_PORT"),
            bind:        get("PUBCAST_WS_BIND"),
            fps:         get("PUBCAST_RENDER_FPS"),
            max_avatars: get("PUBCAST_MAX_AVATARS"),
            ttl:         get("PUBCAST_AVATAR_TTL_SEC"),
            always_emit: get("PUBCAST_ALWAYS_EMIT"),
            callback:    get("PUBCAST_RENDER_CALLBACK"),
            log_level:   get("RUST_LOG"),
            help:        false,
        }
    }

    /// Parse command-line flags. Accepts `--flag value` and `--flag=value`.
    pub fn from_args<I, S>(args: I) -> Result<Self, String>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut s = Self::default();
        let mut it = args.into_iter().map(Into::into);
        while let Some(arg) = it.next() {
            let (flag, inline) = match arg.split_once('=') {
                Some((f, v)) if f.starts_with("--") => (f.to_string(), Some(v.to_string())),
                _ => (arg.clone(), None),
            };
            if flag == "--help" || flag == "-h" {
                s.help = true;
                continue;
            }
            if flag == "--always-emit" {
                s.always_emit = Some(inline.unwrap_or_else(|| "1".to_string()));
                continue;
            }
            let slot = match flag.as_str() {
                "--port"        => &mut s.port,
                "--bind"        => &mut s.bind,
                "--fps"         => &mut s.fps,
                "--max-avatars" => &mut s.max_avatars,
                "--ttl"         => &mut s.ttl,
                "--callback"    => &mut s.callback,
                "--log-level"   => &mut s.log_level,
                other => return Err(format!("unknown argument: {other} (try --help)")),
            };
            let value = match inline {
                Some(v) => v,
                None => it.next().ok_or_else(|| format!("{flag} needs a value"))?,
            };
            *slot = Some(value);
        }
        Ok(s)
    }

    /// Values in `over` win; anything `over` leaves unset comes from `self`.
    pub fn overlay(self, over: Settings) -> Settings {
        Settings {
            port:        over.port.or(self.port),
            bind:        over.bind.or(self.bind),
            fps:         over.fps.or(self.fps),
            max_avatars: over.max_avatars.or(self.max_avatars),
            ttl:         over.ttl.or(self.ttl),
            always_emit: over.always_emit.or(self.always_emit),
            callback:    over.callback.or(self.callback),
            log_level:   over.log_level.or(self.log_level),
            help:        over.help || self.help,
        }
    }

    /// Tracing filter: a bare level applies to this server and the animation
    /// crate; anything containing '=' or ',' is used as a full filter.
    pub fn log_filter(&self) -> String {
        match self.log_level.as_deref().map(str::trim) {
            None | Some("") => DEFAULT_LOG_FILTER.to_string(),
            Some(f) if f.contains('=') || f.contains(',') => f.to_string(),
            Some(lvl) => format!("ws_renderer={lvl},pubcast_animation={lvl}"),
        }
    }

    /// Combine into a config. Bad values are errors, not silent defaults, so a
    /// typo never leaves the server running on a setting nobody asked for.
    /// Returns warnings to log once tracing is up.
    pub fn into_config(&self) -> Result<(RendererConfig, Vec<String>), String> {
        let mut cfg = RendererConfig::default();
        let mut warnings = Vec::new();

        let port = match &self.port {
            Some(p) => p.trim().parse::<u16>()
                .map_err(|_| format!("port must be 0–65535, got {p:?}"))?,
            None => DEFAULT_PORT,
        };
        let ip = match &self.bind {
            Some(b) => b.trim().parse::<IpAddr>()
                .map_err(|_| format!("bind must be an IP address like 127.0.0.1, got {b:?}"))?,
            None => IpAddr::V4(Ipv4Addr::LOCALHOST),
        };
        cfg.listen_addr = SocketAddr::new(ip, port);

        if let Some(f) = &self.fps {
            let v = f.trim().parse::<u32>().map_err(|_| format!("fps must be a whole number, got {f:?}"))?;
            cfg.render_fps = v.clamp(1, 240);
            if cfg.render_fps != v {
                warnings.push(format!("fps {v} out of range; using {}", cfg.render_fps));
            }
        }
        if let Some(m) = &self.max_avatars {
            let v = m.trim().parse::<usize>().map_err(|_| format!("max avatars must be a whole number, got {m:?}"))?;
            cfg.max_avatars = v.clamp(1, 64);
            if cfg.max_avatars != v {
                warnings.push(format!("max avatars {v} out of range; using {}", cfg.max_avatars));
            }
        }
        if let Some(t) = &self.ttl {
            let v = t.trim().parse::<u64>().map_err(|_| format!("ttl must be whole seconds, got {t:?}"))?;
            cfg.avatar_ttl_sec = v.min(3600);
            if cfg.avatar_ttl_sec != v {
                warnings.push(format!("ttl {v}s out of range; using {}s", cfg.avatar_ttl_sec));
            }
        }
        if let Some(a) = &self.always_emit {
            cfg.always_emit = match a.trim().to_ascii_lowercase().as_str() {
                "1" | "true" | "yes" | "on"  => true,
                "0" | "false" | "no" | "off" => false,
                _ => return Err(format!("always-emit must be 1/0, true/false, yes/no or on/off, got {a:?}")),
            };
        }
        if let Some(c) = &self.callback {
            cfg.render_callback = match c.trim().to_ascii_lowercase().as_str() {
                "" | "none" => RenderCallback::None,
                "stdout"    => RenderCallback::Stdout,
                "voxel_bridge" => {
                    warnings.push(
                        "render callback voxel_bridge is not built into this binary; \
                         nothing is forwarded to the voxel engine. Running with callback=none. \
                         Connect the voxel bridge as a render subscriber instead."
                            .to_string(),
                    );
                    RenderCallback::None
                }
                other => return Err(format!("callback must be none, stdout or voxel_bridge, got {other:?}")),
            };
        }
        if !ip.is_loopback() {
            warnings.push(format!(
                "listening on {ip}: other machines on the network can connect, and there is no password"
            ));
        }
        Ok((cfg, warnings))
    }
}

impl RendererConfig {
    /// Build from environment variables only (no flags).
    pub fn from_env() -> Result<Self, String> {
        Settings::from_env().into_config().map(|(c, _)| c)
    }
}

const HELP: &str = "\
PubCast WS Renderer

Flags override environment variables.
  --port N         PUBCAST_WS_PORT          (default 8765)
  --bind ADDR      PUBCAST_WS_BIND          (default 127.0.0.1)
  --fps N          PUBCAST_RENDER_FPS       (default 60, 1-240)
  --max-avatars N  PUBCAST_MAX_AVATARS      (default 16, 1-64)
  --ttl SECONDS    PUBCAST_AVATAR_TTL_SEC   (default 30)
  --always-emit    PUBCAST_ALWAYS_EMIT=1    (default off)
  --callback NAME  PUBCAST_RENDER_CALLBACK  none | stdout (default none)
  --log-level LVL  RUST_LOG                 (default info)
  --help
";

// ─────────────────────────────────────────────────────────────────────────────
// WIRE TYPES
// ─────────────────────────────────────────────────────────────────────────────

/// Ack sent back to the Python client after each received frame.
/// Shape unchanged from the original server so avatar_performer.py keeps working.
#[derive(Debug, Serialize)]
struct FrameAck {
    ok:         bool,
    frame:      u64,
    avatar_id:  String,
    /// Microseconds from receipt to world-matrix recompute
    latency_us: u64,
}

/// Rejection sent instead of a FrameAck.
#[derive(Debug, Serialize)]
struct FrameNack<'a> {
    ok:        bool,
    error:     &'a str,
    avatar_id: Option<&'a str>,
}

/// Non-motion messages a client may send.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlMessage {
    subscribe:   Option<String>,
    unsubscribe: Option<String>,
}

/// World matrices for all joints of one avatar.
#[derive(Debug, Clone, Serialize)]
pub struct RenderedAvatar {
    pub avatar_id:      String,
    pub timestamp:      f64,
    /// Flat array: 16 f32 per joint (column-major 4×4 Matrix4).
    /// Length = joint_count × 16.
    pub world_matrices: Vec<f32>,
    /// Blendshapes: name → weight (0.0–1.0)
    pub blendshapes:    HashMap<String, f32>,
    /// Number of joints (world_matrices.len() / 16)
    pub joint_count:    usize,
    /// Joint names in hierarchy order (matches world_matrices index)
    pub joint_names:    Vec<String>,
    /// Motion frames received for this avatar so far
    pub frame_count:    u64,
}

/// Render tick output.
#[derive(Debug, Clone, Serialize)]
pub struct RenderTick {
    #[serde(rename = "type")]
    pub kind:      &'static str,
    pub tick:      u64,
    pub timestamp: f64,
    /// true: `avatars` is every live avatar. false: only those that changed.
    pub full:      bool,
    pub avatars:   Vec<RenderedAvatar>,
    /// Avatars removed for going silent longer than the TTL this tick
    pub evicted:   Vec<String>,
}

impl RenderTick {
    /// Worth sending to subscribers?
    fn has_news(&self) -> bool {
        self.full || !self.avatars.is_empty() || !self.evicted.is_empty()
    }
}

fn now_unix() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

// ─────────────────────────────────────────────────────────────────────────────
// AVATAR REGISTRY
// ─────────────────────────────────────────────────────────────────────────────

/// One live avatar with its animator and metadata.
struct LiveAvatar {
    animator:    SkeletalAnimator,
    last_update: Instant,
    frame_count: u64,
    /// Blendshapes are passed through separately (not bone transforms)
    blendshapes: HashMap<String, f32>,
    /// Joint names in hierarchy order (cached for output)
    joint_names: Vec<String>,
    /// Pose changed since it was last emitted
    dirty:       bool,
}

impl LiveAvatar {
    fn new(preset: &str) -> Self {
        // Select skeleton based on avatar preset
        let hierarchy = match preset.to_uppercase().as_str() {
            "DOG" => {
                // Dog uses same humanoid rig for now (future: quadruped)
                warn!("DOG preset uses humanoid rig placeholder");
                SkeletonHierarchy::create_pubcast_rig()
            }
            _ => SkeletonHierarchy::create_pubcast_rig(),
        };
        let joint_names: Vec<String> = hierarchy.joints.iter().map(|j| j.name.clone()).collect();
        let animator = SkeletalAnimator::new(hierarchy);
        Self {
            animator,
            last_update: Instant::now(),
            frame_count: 0,
            blendshapes: HashMap::new(),
            joint_names,
            dirty: true,
        }
    }

    fn apply_payload(&mut self, payload: &BridgeMotionPayload) {
        let frame_map = payload.to_mocap_frame();

        // Separate blendshapes (bs_ prefix) from bone transforms.
        // The __preset__ entry is metadata, not a bone.
        let mut bone_data: HashMap<String, Vec<f32>> = HashMap::with_capacity(frame_map.len());
        for (k, v) in frame_map {
            if let Some(name) = k.strip_prefix("bs_") {
                if let Some(&w) = v.first() {
                    self.blendshapes.insert(name.to_string(), w);
                }
            } else if k != "__preset__" {
                bone_data.insert(k, v);
            }
        }

        self.animator.apply_motion_capture_frame(&bone_data);
        self.last_update = Instant::now();
        self.frame_count += 1;
        self.dirty = true;
    }

    fn render(&mut self, avatar_id: &str, timestamp: f64) -> RenderedAvatar {
        let matrices = self.animator.get_world_matrices();
        let world_matrices: Vec<f32> = matrices
            .iter()
            .flat_map(|m| m.as_slice().iter().copied())
            .collect();
        self.dirty = false;

        RenderedAvatar {
            avatar_id:   avatar_id.to_string(),
            timestamp,
            joint_count: world_matrices.len() / 16,
            world_matrices,
            blendshapes: self.blendshapes.clone(),
            joint_names: self.joint_names.clone(),
            frame_count: self.frame_count,
        }
    }

    fn is_stale(&self, ttl: Duration) -> bool {
        self.last_update.elapsed() > ttl
    }
}

/// Why a motion frame was not applied.
#[derive(Debug, PartialEq, Eq)]
enum ApplyError {
    Full { max: usize },
}

impl ApplyError {
    fn message(&self) -> String {
        match self {
            ApplyError::Full { max } => format!("server full: max_avatars ({max}) reached"),
        }
    }
}

/// Thread-safe registry of all live avatars.
#[derive(Clone)]
struct AvatarRegistry {
    inner: Arc<RwLock<HashMap<String, LiveAvatar>>>,
    cfg:   Arc<RendererConfig>,
}

impl AvatarRegistry {
    fn new(cfg: Arc<RendererConfig>) -> Self {
        Self { inner: Arc::new(RwLock::new(HashMap::new())), cfg }
    }

    /// Apply a payload from the Python side. Creates the avatar if new.
    /// Returns the avatar's frame count after this frame.
    async fn apply_payload(&self, payload: &BridgeMotionPayload) -> Result<u64, ApplyError> {
        let mut map = self.inner.write().await;

        if !map.contains_key(&payload.avatar_id) {
            if map.len() >= self.cfg.max_avatars {
                warn!(
                    "Max avatars ({}) reached; refusing new avatar_id={}",
                    self.cfg.max_avatars, payload.avatar_id
                );
                return Err(ApplyError::Full { max: self.cfg.max_avatars });
            }
            let preset = payload
                .motion_data
                .get("__preset__")
                .and_then(|b| b.mesh.as_deref())
                .unwrap_or("MANNY");
            info!("New avatar registered: {} [{}]", payload.avatar_id, preset);
            map.insert(payload.avatar_id.clone(), LiveAvatar::new(preset));
        }

        let avatar = map
            .get_mut(&payload.avatar_id)
            .expect("avatar inserted above while holding the write lock");
        avatar.apply_payload(payload);
        Ok(avatar.frame_count)
    }

    /// Evict stale avatars, then build a tick. With `full`, every avatar is
    /// included; otherwise only avatars changed since their last emit.
    async fn render_tick(&self, tick: u64, full: bool) -> RenderTick {
        let mut map = self.inner.write().await;
        let timestamp = now_unix();

        let ttl = Duration::from_secs(self.cfg.avatar_ttl_sec);
        let evicted: Vec<String> = map
            .iter()
            .filter(|(_, av)| av.is_stale(ttl))
            .map(|(id, _)| id.clone())
            .collect();
        for id in &evicted {
            info!("Evicting stale avatar: {id}");
            map.remove(id);
        }

        let avatars = map
            .iter_mut()
            .filter(|(_, av)| full || av.dirty)
            .map(|(id, av)| av.render(id, timestamp))
            .collect();

        RenderTick { kind: "render_tick", tick, timestamp, full, avatars, evicted }
    }

    /// Full picture for a new subscriber, without evicting or clearing change flags.
    async fn snapshot(&self, tick: u64) -> RenderTick {
        let mut map = self.inner.write().await;
        let timestamp = now_unix();
        let avatars = map
            .iter_mut()
            .map(|(id, av)| {
                let was_dirty = av.dirty;
                let out = av.render(id, timestamp);
                // Keep the change flag so the regular tick still sends this pose
                // to the other subscribers.
                av.dirty = was_dirty;
                out
            })
            .collect();
        RenderTick { kind: "render_tick", tick, timestamp, full: true, avatars, evicted: Vec::new() }
    }

    async fn avatar_count(&self) -> usize {
        self.inner.read().await.len()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SHARED SERVER STATE
// ─────────────────────────────────────────────────────────────────────────────

/// What every connection task needs.
#[derive(Clone)]
struct ServerShared {
    registry:  AvatarRegistry,
    /// Serialized render ticks, shared by all subscribers
    render_tx: broadcast::Sender<Arc<str>>,
    /// Latest tick number, so a snapshot carries a sensible tick
    last_tick: Arc<AtomicU64>,
}

/// Render frames queued per subscriber before the slowest one starts losing
/// frames (about two seconds at 60 fps).
const RENDER_CHANNEL_CAPACITY: usize = 128;

// ─────────────────────────────────────────────────────────────────────────────
// WEBSOCKET CONNECTION HANDLER
// ─────────────────────────────────────────────────────────────────────────────

/// Wait for the next render frame, or forever when not subscribed.
async fn next_render(
    sub: &mut Option<broadcast::Receiver<Arc<str>>>,
) -> Result<Arc<str>, broadcast::error::RecvError> {
    match sub.as_mut() {
        Some(rx) => rx.recv().await,
        None => std::future::pending().await,
    }
}

fn nack(error: &str, avatar_id: Option<&str>) -> String {
    serde_json::to_string(&FrameNack { ok: false, error, avatar_id }).unwrap_or_default()
}

/// Apply a subscribe/unsubscribe request. Returns the messages to send back.
async fn handle_control(
    ctl: ControlMessage,
    shared: &ServerShared,
    render_sub: &mut Option<broadcast::Receiver<Arc<str>>>,
    peer: SocketAddr,
) -> Vec<String> {
    match (ctl.subscribe.as_deref(), ctl.unsubscribe.as_deref()) {
        (Some("render"), None) => {
            if render_sub.is_none() {
                // Subscribe before taking the snapshot so no tick falls between them.
                *render_sub = Some(shared.render_tx.subscribe());
                info!("Render subscriber added: {peer}");
            }
            let snap = shared.registry.snapshot(shared.last_tick.load(Ordering::Relaxed)).await;
            vec![
                serde_json::json!({ "ok": true, "subscribed": "render" }).to_string(),
                serde_json::to_string(&snap).unwrap_or_default(),
            ]
        }
        (None, Some("render")) => {
            if render_sub.take().is_some() {
                info!("Render subscriber removed: {peer}");
            }
            vec![serde_json::json!({ "ok": true, "unsubscribed": "render" }).to_string()]
        }
        _ => vec![nack(
            r#"unknown control message; expected {"subscribe":"render"} or {"unsubscribe":"render"}"#,
            None,
        )],
    }
}

/// Handle one WebSocket connection: a performer, a render subscriber, or both.
/// The task runs until the client disconnects or shutdown is signalled.
async fn handle_connection(
    stream: TcpStream,
    peer: SocketAddr,
    shared: ServerShared,
    mut shutdown: broadcast::Receiver<()>,
) {
    let ws = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            warn!("WebSocket handshake failed from {peer}: {e}");
            return;
        }
    };

    info!("WebSocket connected: {peer}");
    let (mut tx, mut rx) = ws.split();
    let mut render_sub: Option<broadcast::Receiver<Arc<str>>> = None;

    'conn: loop {
        tokio::select! {
            msg = rx.next() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        let t_recv = Instant::now();

                        // Motion frames are the hot path, so try them first.
                        let replies: Vec<String> = match serde_json::from_str::<BridgeMotionPayload>(&text) {
                            Ok(payload) => match shared.registry.apply_payload(&payload).await {
                                Ok(frame_n) => {
                                    let latency = t_recv.elapsed().as_micros() as u64;
                                    debug!("Frame {frame_n} from {peer} processed in {latency}µs");
                                    vec![serde_json::to_string(&FrameAck {
                                        ok: true,
                                        frame: frame_n,
                                        avatar_id: payload.avatar_id,
                                        latency_us: latency,
                                    })
                                    .unwrap_or_default()]
                                }
                                Err(e) => vec![nack(&e.message(), Some(&payload.avatar_id))],
                            },
                            Err(motion_err) => match serde_json::from_str::<ControlMessage>(&text) {
                                Ok(ctl) => handle_control(ctl, &shared, &mut render_sub, peer).await,
                                Err(_) => {
                                    warn!("Bad payload from {peer}: {motion_err}");
                                    vec![nack(&motion_err.to_string(), None)]
                                }
                            },
                        };

                        for r in replies {
                            if tx.send(Message::Text(r)).await.is_err() {
                                break 'conn;
                            }
                        }
                    }

                    Some(Ok(Message::Binary(_))) => {
                        warn!("Binary frames not supported from {peer}; ignoring");
                    }

                    Some(Ok(Message::Ping(data))) => {
                        let _ = tx.send(Message::Pong(data)).await;
                    }

                    Some(Ok(Message::Close(_))) | None => {
                        info!("WebSocket disconnected: {peer}");
                        break;
                    }

                    Some(Ok(_)) => {}   // Pong, Frame variants — ignore

                    Some(Err(e)) => {
                        warn!("WebSocket error from {peer}: {e}");
                        break;
                    }
                }
            }

            frame = next_render(&mut render_sub) => {
                match frame {
                    Ok(json) => {
                        if tx.send(Message::Text(json.to_string())).await.is_err() {
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(n)) => {
                        // Too slow: skip to the newest frames and resend the full
                        // picture so no avatar is left on a stale pose.
                        warn!("Render subscriber {peer} fell behind; skipped {n} tick(s), resyncing");
                        let snap = shared.registry.snapshot(shared.last_tick.load(Ordering::Relaxed)).await;
                        if let Ok(json) = serde_json::to_string(&snap) {
                            if tx.send(Message::Text(json)).await.is_err() {
                                break;
                            }
                        }
                    }
                    Err(broadcast::error::RecvError::Closed) => {
                        render_sub = None;
                    }
                }
            }

            _ = shutdown.recv() => {
                info!("Shutdown: closing connection to {peer}");
                let _ = tx.send(Message::Close(None)).await;
                break;
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// RENDER TICK LOOP
// ─────────────────────────────────────────────────────────────────────────────

/// Runs at `render_fps`, computes world matrices and publishes them to render
/// subscribers and the configured callback.
async fn render_tick_loop(
    shared: ServerShared,
    cfg: Arc<RendererConfig>,
    mut shutdown: broadcast::Receiver<()>,
) {
    let interval_dur = Duration::from_secs_f64(1.0 / cfg.render_fps as f64);
    let mut interval = time::interval(interval_dur);
    interval.set_missed_tick_behavior(time::MissedTickBehavior::Skip);

    let mut tick: u64 = 0;
    let mut last_report = Instant::now();
    let mut emitted_since_report: u64 = 0;

    loop {
        tokio::select! {
            _ = interval.tick() => {
                tick += 1;
                shared.last_tick.store(tick, Ordering::Relaxed);

                let render = shared.registry.render_tick(tick, cfg.always_emit).await;
                if !render.has_news() {
                    continue;
                }

                let want_ws = shared.render_tx.receiver_count() > 0;
                let want_stdout = cfg.render_callback == RenderCallback::Stdout;
                if want_ws || want_stdout {
                    match serde_json::to_string(&render) {
                        Ok(json) => {
                            if want_stdout {
                                println!("{json}");
                            }
                            if want_ws {
                                // Err only means every subscriber left meanwhile.
                                let _ = shared.render_tx.send(Arc::from(json));
                            }
                            emitted_since_report += 1;
                        }
                        Err(e) => error!("Could not serialize render tick {tick}: {e}"),
                    }
                }

                for avatar in &render.avatars {
                    debug!(
                        avatar_id   = %avatar.avatar_id,
                        joints      = avatar.joint_count,
                        blendshapes = avatar.blendshapes.len(),
                        "render_frame"
                    );
                }

                if last_report.elapsed() >= Duration::from_secs(5) {
                    info!(
                        "Render tick {tick}: {} avatar(s) in tick, {emitted_since_report} tick(s) emitted \
                         in the last 5s, {} subscriber(s), interval={:.1}ms",
                        render.avatars.len(),
                        shared.render_tx.receiver_count(),
                        interval_dur.as_secs_f64() * 1000.0,
                    );
                    last_report = Instant::now();
                    emitted_since_report = 0;
                }
            }

            _ = shutdown.recv() => {
                info!("Render tick loop shutting down at tick {tick}");
                break;
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SERVER ENTRY POINT
// ─────────────────────────────────────────────────────────────────────────────

/// Resolves when the process is asked to stop.
async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(e) = tokio::signal::ctrl_c().await {
            error!("Cannot listen for Ctrl+C: {e}");
            std::future::pending::<()>().await;
        }
    };

    #[cfg(unix)]
    let other = async {
        use tokio::signal::unix::{signal, SignalKind};
        match signal(SignalKind::terminate()) {
            Ok(mut s) => { s.recv().await; }
            Err(e) => {
                error!("Cannot listen for SIGTERM: {e}");
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(windows)]
    let other = async {
        match tokio::signal::windows::ctrl_break() {
            Ok(mut s) => { s.recv().await; }
            Err(e) => {
                error!("Cannot listen for Ctrl+Break: {e}");
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(not(any(unix, windows)))]
    let other = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => info!("Ctrl+C received — shutting down gracefully"),
        _ = other  => info!("Termination signal received — shutting down gracefully"),
    }
}

pub async fn run_server(cfg: RendererConfig) -> anyhow::Result<()> {
    let listener = TcpListener::bind(cfg.listen_addr).await?;
    serve(listener, cfg, shutdown_signal()).await
}

/// Run the server on a bound listener until `stop` resolves.
async fn serve<F>(listener: TcpListener, cfg: RendererConfig, stop: F) -> anyhow::Result<()>
where
    F: std::future::Future<Output = ()>,
{
    let cfg = Arc::new(cfg);
    let (render_tx, _) = broadcast::channel::<Arc<str>>(RENDER_CHANNEL_CAPACITY);
    let shared = ServerShared {
        registry: AvatarRegistry::new(Arc::clone(&cfg)),
        render_tx,
        last_tick: Arc::new(AtomicU64::new(0)),
    };

    info!("PubCast WS Renderer listening on {}", listener.local_addr()?);
    info!(
        "Render target: {}fps  Max avatars: {}  TTL: {}s  Always emit: {}  Callback: {:?}",
        cfg.render_fps, cfg.max_avatars, cfg.avatar_ttl_sec, cfg.always_emit, cfg.render_callback
    );

    // Shutdown broadcast: send () to all tasks to begin clean teardown
    let (shutdown_tx, _) = broadcast::channel::<()>(1);
    let mut tasks = tokio::task::JoinSet::new();

    {
        let shared = shared.clone();
        let cfg = Arc::clone(&cfg);
        let rx = shutdown_tx.subscribe();
        tasks.spawn(async move { render_tick_loop(shared, cfg, rx).await });
    }
    {
        let reg = shared.registry.clone();
        let rx = shutdown_tx.subscribe();
        tasks.spawn(async move { stats_logger(reg, rx).await });
    }

    tokio::pin!(stop);
    loop {
        tokio::select! {
            result = listener.accept() => {
                match result {
                    Ok((stream, peer)) => {
                        let shared = shared.clone();
                        let rx = shutdown_tx.subscribe();
                        tasks.spawn(async move { handle_connection(stream, peer, shared, rx).await });
                    }
                    Err(e) => {
                        error!("TCP accept error: {e}");
                        // Avoid a hot loop if accept keeps failing (e.g. out of file handles)
                        time::sleep(Duration::from_millis(50)).await;
                    }
                }
            }
            _ = &mut stop => {
                let _ = shutdown_tx.send(());
                break;
            }
        }
    }

    // Let tasks finish their close frames, but don't hang on a stuck client.
    let drained = time::timeout(Duration::from_secs(2), async {
        while tasks.join_next().await.is_some() {}
    })
    .await;
    if drained.is_err() {
        warn!("Some connections did not close within 2s; stopping anyway");
        tasks.abort_all();
    }
    info!("PubCast WS Renderer stopped");
    Ok(())
}

async fn stats_logger(registry: AvatarRegistry, mut shutdown: broadcast::Receiver<()>) {
    let mut interval = time::interval(Duration::from_secs(30));
    loop {
        tokio::select! {
            _ = interval.tick() => {
                let n = registry.avatar_count().await;
                info!("Registry: {n} live avatar(s)");
            }
            _ = shutdown.recv() => break,
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// BINARY ENTRY POINT
// ─────────────────────────────────────────────────────────────────────────────

/// Add to Cargo.toml:
/// ```toml
/// [[bin]]
/// name = "ws_renderer"
/// path = "src/ws_renderer.rs"
/// ```
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = match Settings::from_args(std::env::args().skip(1)) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ws_renderer: {e}");
            std::process::exit(2);
        }
    };
    if args.help {
        print!("{HELP}");
        return Ok(());
    }
    let settings = Settings::from_env().overlay(args);

    // Logs go to stderr so stdout stays clean for --callback stdout.
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::new(settings.log_filter()))
        .with_writer(std::io::stderr)
        .with_target(false)
        .compact()
        .init();

    let (cfg, warnings) = match settings.into_config() {
        Ok(c) => c,
        Err(e) => {
            error!("Configuration error: {e}");
            std::process::exit(2);
        }
    };
    for w in warnings {
        warn!("{w}");
    }

    run_server(cfg).await
}

// ─────────────────────────────────────────────────────────────────────────────
// TESTS
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use pubcast_animation::BridgeBoneData;

    fn bone(position: [f32; 3]) -> BridgeBoneData {
        BridgeBoneData {
            position,
            rotation:   [0.0, 0.0, 0.0, 1.0],
            mesh:       None,
            shape_type: None,
            confidence: Some(0.98),
        }
    }

    fn make_payload(avatar_id: &str) -> BridgeMotionPayload {
        let mut motion = HashMap::new();
        motion.insert("Pelvis".to_string(), bone([0.0, 0.95, 0.0]));
        motion.insert("Spine_01".to_string(), bone([0.0, 1.03, 0.0]));
        // Blendshape via bs_ key; weight in position[0]
        motion.insert("bs_eyeBlinkLeft".to_string(), bone([0.35, 0.0, 0.0]));
        BridgeMotionPayload {
            avatar_id:   avatar_id.to_string(),
            motion_data: motion,
            timestamp:   1_234_567_890.0,
        }
    }

    fn registry(cfg: RendererConfig) -> AvatarRegistry {
        AvatarRegistry::new(Arc::new(cfg))
    }

    #[tokio::test]
    async fn test_avatar_registry_creates_on_first_payload() {
        let reg = registry(RendererConfig::default());
        assert_eq!(reg.apply_payload(&make_payload("avatar_01")).await, Ok(1));
        assert_eq!(reg.avatar_count().await, 1);
    }

    #[tokio::test]
    async fn test_avatar_registry_max_avatars_enforced_and_reported() {
        let reg = registry(RendererConfig { max_avatars: 2, ..Default::default() });
        let mut results = Vec::new();
        for i in 0..5 {
            results.push(reg.apply_payload(&make_payload(&format!("av_{i}"))).await);
        }
        assert_eq!(reg.avatar_count().await, 2);
        assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 2);
        assert!(results[2..].iter().all(|r| *r == Err(ApplyError::Full { max: 2 })));
        // An avatar already in the room keeps working when the room is full.
        assert_eq!(reg.apply_payload(&make_payload("av_0")).await, Ok(2));
    }

    #[tokio::test]
    async fn test_blendshape_extracted_from_bs_prefix() {
        let reg = registry(RendererConfig::default());
        reg.apply_payload(&make_payload("test_av")).await.unwrap();
        let map = reg.inner.read().await;
        let weight = map["test_av"].blendshapes["eyeBlinkLeft"];
        assert!((weight - 0.35).abs() < 1e-5, "got {weight}");
    }

    #[tokio::test]
    async fn test_render_tick_produces_world_matrices() {
        let reg = registry(RendererConfig::default());
        reg.apply_payload(&make_payload("render_test")).await.unwrap();

        let tick = reg.render_tick(1, false).await;
        assert_eq!(tick.avatars.len(), 1);
        let avatar = &tick.avatars[0];
        assert_eq!(avatar.avatar_id, "render_test");
        assert!(!avatar.world_matrices.is_empty());
        assert_eq!(avatar.world_matrices.len(), avatar.joint_count * 16);
        assert!(avatar.world_matrices.iter().all(|v| v.is_finite()));
    }

    #[tokio::test]
    async fn test_render_tick_change_only_and_always_emit() {
        let reg = registry(RendererConfig::default());
        reg.apply_payload(&make_payload("a")).await.unwrap();

        assert_eq!(reg.render_tick(1, false).await.avatars.len(), 1, "new pose is emitted");
        let quiet = reg.render_tick(2, false).await;
        assert!(quiet.avatars.is_empty() && !quiet.has_news(), "unchanged pose is not re-sent");
        assert_eq!(reg.render_tick(3, true).await.avatars.len(), 1, "always_emit sends it anyway");

        reg.apply_payload(&make_payload("a")).await.unwrap();
        assert_eq!(reg.render_tick(4, false).await.avatars.len(), 1, "changed again, emitted again");
    }

    #[tokio::test]
    async fn test_snapshot_does_not_swallow_pending_change() {
        let reg = registry(RendererConfig::default());
        reg.apply_payload(&make_payload("a")).await.unwrap();
        assert_eq!(reg.snapshot(0).await.avatars.len(), 1);
        assert_eq!(reg.render_tick(1, false).await.avatars.len(), 1,
            "a snapshot for one subscriber must not hide the change from the others");
    }

    #[tokio::test]
    async fn test_render_tick_incremental_updates() {
        let reg = registry(RendererConfig::default());
        for _ in 0..10 {
            reg.apply_payload(&make_payload("av_inc")).await.unwrap();
        }
        assert_eq!(reg.inner.read().await["av_inc"].frame_count, 10);
    }

    #[tokio::test]
    async fn test_stale_avatar_eviction_is_reported() {
        let reg = registry(RendererConfig { avatar_ttl_sec: 0, ..Default::default() });
        reg.apply_payload(&make_payload("stale_av")).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        let tick = reg.render_tick(1, false).await;
        assert!(tick.avatars.is_empty());
        assert_eq!(tick.evicted, vec!["stale_av".to_string()]);
        assert!(tick.has_news(), "subscribers must hear about the eviction");
        assert_eq!(reg.avatar_count().await, 0);
    }

    #[test]
    fn test_flags_parse_and_override_env() {
        let env = Settings { port: Some("9000".into()), fps: Some("30".into()), ..Default::default() };
        let args = Settings::from_args(["--port", "8770", "--log-level=debug", "--always-emit"]).unwrap();
        let s = env.overlay(args);
        let (cfg, _) = s.into_config().unwrap();
        assert_eq!(cfg.listen_addr.port(), 8770, "flag beats env");
        assert_eq!(cfg.render_fps, 30, "env used where no flag");
        assert!(cfg.always_emit);
        assert_eq!(s.log_filter(), "ws_renderer=debug,pubcast_animation=debug");
    }

    #[test]
    fn test_bad_input_is_an_error_not_a_silent_default() {
        assert!(Settings::from_args(["--prot", "1"]).is_err(), "typo in flag name");
        assert!(Settings::from_args(["--port"]).is_err(), "missing value");
        let bad = Settings { port: Some("87650".into()), ..Default::default() };
        assert!(bad.into_config().is_err(), "port out of range");
        let bad = Settings { callback: Some("vox".into()), ..Default::default() };
        assert!(bad.into_config().is_err());
    }

    #[test]
    fn test_defaults_are_local_only_and_log_visibly() {
        let (cfg, warnings) = Settings::default().into_config().unwrap();
        assert_eq!(cfg.listen_addr.port(), 8765);
        assert!(cfg.listen_addr.ip().is_loopback());
        assert!(warnings.is_empty());
        assert_eq!(Settings::default().log_filter(), DEFAULT_LOG_FILTER);

        let open = Settings { bind: Some("0.0.0.0".into()), ..Default::default() };
        let (_, warnings) = open.into_config().unwrap();
        assert!(warnings.iter().any(|w| w.contains("no password")));
    }

    #[test]
    fn test_voxel_bridge_callback_is_reported_not_faked() {
        let s = Settings { callback: Some("voxel_bridge".into()), ..Default::default() };
        let (cfg, warnings) = s.into_config().unwrap();
        assert_eq!(cfg.render_callback, RenderCallback::None);
        assert!(warnings.iter().any(|w| w.contains("not built into this binary")));
    }

    /// End to end over a real socket: a performer streams, a subscriber
    /// receives the snapshot and live ticks, and a full server says no.
    #[tokio::test]
    async fn test_websocket_performer_and_subscriber() {
        use tokio_tungstenite::connect_async;

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let (stop_tx, stop_rx) = tokio::sync::oneshot::channel::<()>();
        let cfg = RendererConfig { max_avatars: 1, render_fps: 120, ..Default::default() };
        let server = tokio::spawn(serve(listener, cfg, async { let _ = stop_rx.await; }));

        let url = format!("ws://{addr}");
        let (mut perf, _) = connect_async(&url).await.unwrap();
        let (mut sub, _) = connect_async(&url).await.unwrap();

        async fn next_json<S>(ws: &mut S) -> serde_json::Value
        where
            S: StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>> + Unpin,
        {
            loop {
                let msg = time::timeout(Duration::from_secs(3), ws.next())
                    .await
                    .expect("timed out")
                    .unwrap()
                    .unwrap();
                if let Message::Text(t) = msg {
                    return serde_json::from_str(&t).unwrap();
                }
            }
        }

        // Subscribe: ok, then an (empty) full snapshot.
        sub.send(Message::Text(r#"{"subscribe":"render"}"#.into())).await.unwrap();
        assert_eq!(next_json(&mut sub).await["subscribed"], "render");
        let snap = next_json(&mut sub).await;
        assert_eq!(snap["type"], "render_tick");
        assert_eq!(snap["full"], true);

        // Performer frame is acked exactly as before.
        let frame = serde_json::to_string(&make_payload("live")).unwrap();
        perf.send(Message::Text(frame)).await.unwrap();
        let ack = next_json(&mut perf).await;
        assert_eq!(ack["ok"], true);
        assert_eq!(ack["frame"], 1);
        assert_eq!(ack["avatar_id"], "live");

        // Subscriber gets the pose on a following tick.
        let tick = loop {
            let t = next_json(&mut sub).await;
            if t["avatars"].as_array().map_or(false, |a| !a.is_empty()) {
                break t;
            }
        };
        assert_eq!(tick["avatars"][0]["avatar_id"], "live");
        let n = tick["avatars"][0]["joint_count"].as_u64().unwrap() as usize;
        assert_eq!(tick["avatars"][0]["world_matrices"].as_array().unwrap().len(), n * 16);

        // Second avatar on a full server: refused, and told so.
        let other = serde_json::to_string(&make_payload("second")).unwrap();
        perf.send(Message::Text(other)).await.unwrap();
        let refused = next_json(&mut perf).await;
        assert_eq!(refused["ok"], false);
        assert_eq!(refused["avatar_id"], "second");

        // Garbage gets an error reply, not silence.
        perf.send(Message::Text("not json".into())).await.unwrap();
        assert_eq!(next_json(&mut perf).await["ok"], false);

        stop_tx.send(()).unwrap();
        time::timeout(Duration::from_secs(5), server).await.unwrap().unwrap().unwrap();
    }
}
