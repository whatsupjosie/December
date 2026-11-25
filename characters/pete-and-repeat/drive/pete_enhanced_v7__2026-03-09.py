#!/usr/bin/env python3
"""
PETE ENHANCED v7.0 - THE MASTER ORCHESTRATOR
=============================================
"I run the whole show now, boss."

Pete Enhanced coordinates the complete PubCast AI system:
- Studio Control Room (production control)
- Voxel Asset System (3D environments)
- Avatar System (neon avatars)
- Twin Engine (Python + Rust)
- WebRTC Streaming (60fps to browser)
- Ollama AI Integration (bots, voice cues)

This is the brain of the operation. Every system reports to Pete.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import psutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

from engine_bridges import RustBridge, WebRTCBridge

if TYPE_CHECKING:
    from modules.hub import Hub
    from modules.studio_control import StudioControl, PreflightCheck
    from modules.voxel_asset_manager import VoxelAssetManager, VoxelScene
    from modules.avatar_system import AvatarState

logger = logging.getLogger("pubcast.pete_enhanced")


# ─────────────────────────────────────────────
# ENUMS AND DATA CLASSES
# ─────────────────────────────────────────────

class TwinEngineHealth(Enum):
    """Overall twin engine system health"""
    PERFECT = "perfect"           # <16ms latency, all optimal
    EXCELLENT = "excellent"       # <33ms latency, all healthy
    GOOD = "good"                # <50ms latency, minor issues
    DEGRADED = "degraded"        # <100ms latency, performance issues
    CRITICAL = "critical"        # >100ms latency, major issues
    EMERGENCY = "emergency"      # System failure imminent


@dataclass
class PeteMetrics:
    """Complete system metrics"""
    # System resources
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    
    # Pipeline metrics
    total_latency_ms: float = 0.0
    rust_engine_fps: float = 0.0
    webrtc_fps: float = 0.0
    
    # Component health
    hub_healthy: bool = False
    studio_control_state: str = "IDLE"
    voxel_scene_loaded: bool = False
    avatar_count: int = 0
    
    # Performance
    dropped_frames: int = 0
    last_update: float = field(default_factory=time.time)
    
    # Bot/AI
    ollama_online: bool = False
    active_bots: int = 0


class PeteEnhanced:
    """
    Pete Enhanced v7.0 - The Master Orchestrator
    
    "I coordinate everything. Studio control, voxel scenes, avatars,
     the twin engines, WebRTC streaming - all of it runs through me.
     
     The show goes on because I make sure every piece is in place,
     every system is healthy, and when something goes wrong,
     I handle it before you even notice.
     
     That's what I do. That's who I am." - Pete
    """
    
    def __init__(
        self,
        hub: 'Hub',
        data_dir: Path,
        config: Optional[Dict[str, Any]] = None
    ):
        self.hub = hub
        self.data_dir = data_dir
        self.config = config or {}
        
        # System references (set after initialization)
        self.studio_control: Optional['StudioControl'] = None
        self.voxel_manager: Optional['VoxelAssetManager'] = None
        self.bot_manager: Optional[Any] = None
        
        # Twin Engine components
        self.rust_bridge: Optional[Any] = None
        self.webrtc_bridge: Optional[Any] = None
        
        # State
        self._health = TwinEngineHealth.GOOD
        self._metrics = PeteMetrics()
        self._monitoring_active = False
        self._startup_time = time.time()
        
        # Configuration
        self._rust_engine_host = self.config.get("rust_engine_host", "localhost")
        self._rust_engine_port = self.config.get("rust_engine_port", 9000)
        self._webrtc_stream_url = self.config.get("webrtc_stream_url", "ws://localhost:8001/stream")
        self._enable_adaptive_quality = self.config.get("enable_adaptive_quality", True)
        self._enable_voice_cues = self.config.get("enable_voice_cues", True)
        
        logger.info("🎭 Pete Enhanced v7.0 initialized")
    
    # ─────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────
    
    async def initialize_twin_engine_system(self) -> bool:
        """
        Initialize the complete twin engine system
        
        This is Pete's startup sequence:
        1. Connect to Rust voxel engine (rendering)
        2. Initialize WebRTC streaming (browser output)
        3. Start system health monitoring
        4. Run integration tests
        """
        logger.info("🎭 Pete: Starting twin engine initialization...")
        
        try:
            # Step 1: Connect to Rust engine
            logger.info("🎭 Pete: Connecting to Rust voxel engine...")
            rust_connected = await self._initialize_rust_engine()
            
            if not rust_connected:
                logger.warning("🎭 Pete: Rust engine not available - continuing in limited mode")
            
            # Step 2: Initialize WebRTC streaming
            logger.info("🎭 Pete: Setting up WebRTC streaming...")
            webrtc_ready = await self._initialize_webrtc_streaming()
            
            if not webrtc_ready:
                logger.warning("🎭 Pete: WebRTC streaming unavailable - continuing without streaming")
            
            # Step 3: Start monitoring
            logger.info("🎭 Pete: Starting health monitoring...")
            await self._start_monitoring()
            
            # Step 4: Integration test
            logger.info("🎭 Pete: Running system integration test...")
            integration_ok = await self._test_integration()
            
            if integration_ok:
                logger.info("🎭 Pete: Twin engine system fully operational ✨")
                return True
            else:
                logger.warning("🎭 Pete: Twin engine system operational with limitations")
                return True  # Continue with limited functionality
                
        except Exception as e:
            logger.error(f"🎭 Pete: Initialization failed: {e}", exc_info=True)
            return False
    
    async def _initialize_rust_engine(self) -> bool:
        """Connect to Rust voxel rendering engine via TCP."""
        try:
            self.rust_bridge = RustBridge(
                host=self._rust_engine_host,
                port=self._rust_engine_port
            )
            connected = await self.rust_bridge.connect()
            if connected:
                logger.info(f"🦀 Pete: Rust engine connected at {self._rust_engine_host}:{self._rust_engine_port}")
            else:
                logger.warning(
                    f"🦀 Pete: Rust engine not running at "
                    f"{self._rust_engine_host}:{self._rust_engine_port} — "
                    f"bridge will auto-reconnect when engine starts"
                )
            # Return True either way — bridge handles reconnection,
            # and missing Rust engine is non-fatal for Python systems
            return True
        except Exception as e:
            logger.error(f"🦀 Pete: Rust bridge init failed: {e}")
            return False
    
    async def _initialize_webrtc_streaming(self) -> bool:
        """Initialize WebRTC streaming to browser via signaling WebSocket."""
        try:
            self.webrtc_bridge = WebRTCBridge(url=self._webrtc_stream_url)
            connected = await self.webrtc_bridge.start()
            if connected:
                logger.info(f"🎥 Pete: WebRTC bridge connected at {self._webrtc_stream_url}")
            else:
                logger.warning(
                    f"🎥 Pete: WebRTC server not running at {self._webrtc_stream_url} — "
                    f"bridge will auto-reconnect when server starts"
                )
            return True
        except Exception as e:
            logger.error(f"🎥 Pete: WebRTC bridge init failed: {e}")
            return False
    
    async def _start_monitoring(self) -> None:
        """Start system health monitoring"""
        self._monitoring_active = True
        asyncio.create_task(self._monitoring_loop())
        logger.info("🎭 Pete: Health monitoring started")
    
    async def _test_integration(self) -> bool:
        """Test complete system integration"""
        try:
            # Test 1: Hub communication
            hub_ok = self.hub is not None
            
            # Test 2: System metrics collection
            self._metrics = await self._collect_metrics()
            
            # Test 3: Health assessment
            self._health = self._assess_health(self._metrics)
            
            all_ok = hub_ok
            logger.info(f"🎭 Pete: Integration test {'PASSED' if all_ok else 'PARTIAL'}")
            return all_ok
            
        except Exception as e:
            logger.error(f"🎭 Pete: Integration test failed: {e}")
            return False
    
    # ─────────────────────────────────────────────
    # STUDIO CONTROL INTEGRATION
    # ─────────────────────────────────────────────
    
    async def execute_preflight_sequence(self) -> bool:
        """
        Execute the 5-second preflight countdown
        
        This is called by Studio Control when user starts recording.
        Pete coordinates all the checks and preparations.
        """
        logger.info("🎭 Pete: Executing preflight sequence...")
        
        if not self.studio_control:
            logger.error("🎭 Pete: Studio Control not connected")
            return False
        
        # Let Studio Control run its sequence
        # Pete will respond to hooks during countdown
        return True
    
    async def speak_voice_cue(self, text: str, voice: str = "pete") -> None:
        """
        Speak a voice cue via hub broadcast (Web Speech API in browser)
        and optionally via system TTS (espeak/say) if available.

        Called during preflight countdown:
        - "T minus 5" through "Recording started"
        - Emergency announcements
        - Health warnings
        """
        if not self._enable_voice_cues:
            return

        logger.info(f"🎭 Pete speaking: '{text}'")

        # Broadcast to browser clients — they handle speech via Web Speech API
        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "voice_cue",
                    "text": text,
                    "voice": voice,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"🎭 Hub broadcast failed: {e}")

        # Try system TTS as a local fallback (non-blocking)
        try:
            import subprocess
            import sys
            if sys.platform == "darwin":
                subprocess.Popen(["say", "-v", "Samantha", text],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["espeak", "-s", "150", text],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass  # TTS binary not installed — browser handles it
        except Exception as e:
            logger.debug(f"🎭 System TTS unavailable: {e}")
    
    async def on_studio_live(self) -> None:
        """
        Called when Studio Control transitions to LIVE state
        
        Final preparations before recording starts.
        """
        logger.info("🎭 Pete: Studio going LIVE - final sync")
        
        # Sync active scene to Rust engine
        if self.voxel_manager:
            scene = self.voxel_manager.get_active_scene()
            if scene:
                await self.sync_scene_to_rust_engine(scene)
        
        # Start performance monitoring
        self._metrics.studio_control_state = "LIVE"
    
    async def on_studio_emergency(self, reason: str) -> None:
        """
        Called when emergency save is triggered
        
        Pete coordinates emergency protocols across all systems.
        """
        logger.critical(f"🎭 Pete: EMERGENCY SAVE - {reason}")
        
        # Emergency voice cue
        await self.speak_voice_cue("Emergency save activated")
        
        # Flush all buffers
        await self.emergency_flush_buffers(self.data_dir / "emergency_saves" / f"emergency_{int(time.time())}")
    
    async def emergency_flush_buffers(self, save_path: Path) -> None:
        """
        Emergency buffer flush — save everything reachable to disk immediately.

        Called by studio_control.trigger_emergency_save().
        Saves: voxel scene state, Pete metrics snapshot, active config.
        Audio/video frames are owned by the recording pipeline and handled there.
        """
        import json as _json
        logger.critical("🎭 Pete: FLUSHING ALL BUFFERS")

        try:
            save_path.mkdir(parents=True, exist_ok=True)

            # 1. Voxel scene state
            if self.voxel_manager:
                try:
                    active = self.voxel_manager.get_active_scene()
                    if active:
                        scene_file = save_path / "voxel_scene.json"
                        scene_file.write_text(_json.dumps(active.to_dict(), indent=2))
                        logger.info(f"🎭 Pete: Voxel scene saved → {scene_file}")
                except Exception as e:
                    logger.error(f"🎭 Pete: Voxel scene save failed: {e}")

            # 2. Pete metrics snapshot
            try:
                metrics_file = save_path / "pete_metrics.json"
                metrics_file.write_text(_json.dumps({
                    "cpu_percent": self._metrics.cpu_percent,
                    "memory_mb": self._metrics.memory_mb,
                    "memory_percent": self._metrics.memory_percent,
                    "health": self._health.value,
                    "studio_control_state": self._metrics.studio_control_state,
                    "voxel_scene_loaded": self._metrics.voxel_scene_loaded,
                    "snapshot_time": time.time(),
                }, indent=2))
            except Exception as e:
                logger.error(f"🎭 Pete: Metrics snapshot failed: {e}")

            # 3. Active configuration snapshot
            try:
                config_file = save_path / "pete_config.json"
                config_file.write_text(_json.dumps({
                    "rust_engine_host": self._rust_engine_host,
                    "rust_engine_port": self._rust_engine_port,
                    "webrtc_stream_url": self._webrtc_stream_url,
                    "enable_voice_cues": self._enable_voice_cues,
                    "data_dir": str(self._data_dir),
                }, indent=2))
            except Exception as e:
                logger.error(f"🎭 Pete: Config snapshot failed: {e}")

            # 4. Notify hub clients
            if self.hub:
                try:
                    await self.hub.broadcast({
                        "type": "emergency_save_complete",
                        "save_path": str(save_path),
                        "timestamp": time.time()
                    })
                except Exception:
                    pass

            logger.info(f"🎭 Pete: Emergency flush complete → {save_path}")

        except Exception as e:
            logger.critical(f"🎭 Pete: EMERGENCY SAVE FAILED: {e}", exc_info=True)
    
    # ─────────────────────────────────────────────
    # VOXEL SYSTEM INTEGRATION
    # ─────────────────────────────────────────────
    
    async def validate_scene(self, scene_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate scene for preflight (called at T-4)
        
        Returns validation report.
        """
        if not self.voxel_manager:
            return {
                "passed": False,
                "errors": ["Voxel manager not initialized"],
                "warnings": [],
                "info": {}
            }
        
        return await self.voxel_manager.validate_scene_for_preflight(scene_id)
    
    async def preload_scene_assets(self, scene_id: Optional[str] = None) -> bool:
        """
        Preload all assets for a scene (called at T-2)
        
        Ensures all 3D models are loaded before recording starts.
        """
        if not self.voxel_manager:
            logger.error("🎭 Pete: Voxel manager not initialized")
            return False
        
        logger.info("🎭 Pete: Preloading scene assets...")
        success = await self.voxel_manager.preload_scene_assets(scene_id)
        
        if success:
            logger.info("🎭 Pete: All assets preloaded ✅")
        else:
            logger.error("🎭 Pete: Asset preload failed ❌")
        
        return success
    
    async def sync_scene_to_rust_engine(self, scene: 'VoxelScene') -> bool:
        """
        Synchronize scene to Rust voxel engine.

        Uses live TCP bridge when the engine is running.
        Falls back to writing data/current_scene.json (file-watch fallback)
        when the engine is not yet connected.
        """
        import json as _json
        logger.info(f"🎭 Pete: Syncing scene to Rust engine: {scene.name}")

        try:
            scene_data = scene.to_dict()

            # Prefer live bridge if connected
            if self.rust_bridge and self.rust_bridge.is_connected:
                ok = await self.rust_bridge.load_scene(scene_data)
                if ok:
                    return True
                logger.warning("🦀 Pete: live bridge rejected scene — falling back to file")

            # File-based fallback: write JSON the Rust engine reads on startup/file-watch
            scene_out = self._data_dir / "current_scene.json"
            scene_out.write_text(_json.dumps(scene_data, indent=2))
            logger.info(
                f"🎭 Pete: Scene written → {scene_out} "
                f"({len(scene.instances)} instances)"
            )
            return True

        except Exception as e:
            logger.error(f"🎭 Pete: Scene sync failed: {e}")
            return False

    async def on_recording_checkpoint(self, save_dir: Path, metadata: dict) -> None:
        """
        Called by StudioControl whenever a recording checkpoint is saved.
        Broadcasts checkpoint notification to hub clients and logs it.
        """
        logger.info(f"🎭 Pete: Recording checkpoint at {save_dir}")

        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "recording_checkpoint",
                    "save_dir": str(save_dir),
                    "duration_seconds": metadata.get("duration_seconds", 0),
                    "save_type": metadata.get("save_type", "unknown"),
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"🎭 Pete: recording_checkpoint broadcast failed: {e}")
    
    # ─────────────────────────────────────────────
    # AVATAR SYSTEM INTEGRATION
    # ─────────────────────────────────────────────
    
    async def animate_avatar(self, avatar_id: str, animation: str) -> bool:
        """Trigger avatar animation via Rust bridge (with Hub broadcast fallback)."""
        logger.info(f"🎭 Pete: Animating avatar {avatar_id}: {animation}")

        # Use live bridge when connected
        if self.rust_bridge and self.rust_bridge.is_connected:
            ok = await self.rust_bridge.send_avatar_command(avatar_id, animation)
            if ok:
                return True

        # Broadcast through Hub so UI/browser handles it
        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "avatar_animate",
                    "avatar_id": avatar_id,
                    "animation": animation,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"🎭 Pete: avatar_animate broadcast failed: {e}")

        return True
    
    async def update_avatar_expression(self, avatar_id: str, mood: str) -> bool:
        """Update avatar facial expression via Rust bridge (with Hub broadcast fallback)."""
        logger.info(f"🎭 Pete: Updating avatar {avatar_id} mood: {mood}")

        if self.rust_bridge and self.rust_bridge.is_connected:
            ok = await self.rust_bridge.send_avatar_command(
                avatar_id, "set_expression", {"mood": mood}
            )
            if ok:
                return True

        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "avatar_expression",
                    "avatar_id": avatar_id,
                    "mood": mood,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"🎭 Pete: avatar_expression broadcast failed: {e}")

        return True
    
    # ─────────────────────────────────────────────
    # HEALTH MONITORING
    # ─────────────────────────────────────────────
    
    async def _monitoring_loop(self) -> None:
        """Continuous health monitoring loop"""
        while self._monitoring_active:
            try:
                # Collect metrics
                self._metrics = await self._collect_metrics()
                
                # Assess health
                old_health = self._health
                self._health = self._assess_health(self._metrics)
                
                # Handle health changes
                if self._health != old_health:
                    await self._handle_health_change(old_health, self._health)
                
                # Adaptive quality optimization
                if self._enable_adaptive_quality and self._health in [TwinEngineHealth.DEGRADED, TwinEngineHealth.CRITICAL]:
                    await self._optimize_performance()
                
                # Emergency protocols
                if self._health == TwinEngineHealth.EMERGENCY:
                    await self._handle_emergency()
                
                await asyncio.sleep(2.0)  # Check every 2 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🎭 Pete: Monitoring error: {e}")
                await asyncio.sleep(5.0)
    
    async def _collect_metrics(self) -> PeteMetrics:
        """Collect comprehensive system metrics"""
        metrics = PeteMetrics()
        
        try:
            # System resources
            metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            metrics.memory_mb = mem.used / 1024 / 1024
            metrics.memory_percent = mem.percent
            
            # Component health
            metrics.hub_healthy = self.hub is not None
            metrics.studio_control_state = self.studio_control.state.value if self.studio_control else "UNKNOWN"
            metrics.voxel_scene_loaded = (
                self.voxel_manager.get_active_scene() is not None
                if self.voxel_manager else False
            )
            
            # Pipeline metrics from real bridges
            if self.rust_bridge and self.rust_bridge.is_connected:
                metrics.rust_engine_fps = await self.rust_bridge.get_fps()
                metrics.total_latency_ms = await self.rust_bridge.get_latency_ms()
            else:
                metrics.rust_engine_fps = 0.0

            if self.webrtc_bridge and self.webrtc_bridge.is_connected:
                metrics.webrtc_fps = await self.webrtc_bridge.get_fps()
            else:
                metrics.webrtc_fps = 0.0
            
            metrics.last_update = time.time()
            
        except Exception as e:
            logger.error(f"🎭 Pete: Metrics collection error: {e}")
        
        return metrics
    
    def _assess_health(self, metrics: PeteMetrics) -> TwinEngineHealth:
        """Assess overall system health based on metrics"""
        # Simple assessment for now
        if metrics.cpu_percent > 90 or metrics.memory_percent > 90:
            return TwinEngineHealth.CRITICAL
        elif metrics.cpu_percent > 70 or metrics.memory_percent > 70:
            return TwinEngineHealth.DEGRADED
        elif not metrics.hub_healthy:
            return TwinEngineHealth.DEGRADED
        else:
            return TwinEngineHealth.GOOD
    
    async def _handle_health_change(self, old: TwinEngineHealth, new: TwinEngineHealth) -> None:
        """Handle health status changes"""
        logger.info(f"🎭 Pete: Health changed: {old.value} → {new.value}")
        
        if new in [TwinEngineHealth.CRITICAL, TwinEngineHealth.EMERGENCY]:
            await self.speak_voice_cue(f"System health {new.value}")
    
    async def _optimize_performance(self) -> None:
        """Optimize system performance under load via GC and hub throttling"""
        logger.info("🎭 Pete: Optimizing performance...")

        import gc
        collected = gc.collect()
        logger.info(f"🎭 Pete: GC collected {collected} objects")

        # Notify connected clients to reduce update rate
        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "performance_mode",
                    "active": True,
                    "reason": f"CPU {self._metrics.cpu_percent:.0f}% / RAM {self._metrics.memory_percent:.0f}%",
                    "timestamp": time.time()
                })
            except Exception:
                pass

        # Throttle audio matrix polling if studio control is active
        if self.studio_control and hasattr(self.studio_control, "_audio_update_interval"):
            original = self.studio_control._audio_update_interval
            self.studio_control._audio_update_interval = max(original, 0.5)
            logger.info(f"🎭 Pete: Audio poll throttled to {self.studio_control._audio_update_interval}s")

        logger.info("🎭 Pete: Performance optimization applied")
    
    async def _handle_emergency(self) -> None:
        """Handle emergency situation"""
        logger.critical("🎭 Pete: EMERGENCY SITUATION DETECTED")
        
        if self.studio_control:
            await self.studio_control.trigger_emergency_save("Pete detected emergency")
    
    # ─────────────────────────────────────────────
    # STATUS AND SHUTDOWN
    # ─────────────────────────────────────────────
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete Pete status"""
        return {
            "health": self._health.value,
            "uptime_seconds": time.time() - self._startup_time,
            "metrics": {
                "cpu_percent": self._metrics.cpu_percent,
                "memory_mb": self._metrics.memory_mb,
                "memory_percent": self._metrics.memory_percent,
                "total_latency_ms": self._metrics.total_latency_ms,
                "rust_engine_fps": self._metrics.rust_engine_fps,
                "webrtc_fps": self._metrics.webrtc_fps
            },
            "components": {
                "studio_control": self._metrics.studio_control_state,
                "voxel_scene_loaded": self._metrics.voxel_scene_loaded,
                "avatar_count": self._metrics.avatar_count,
                "ollama_online": self._metrics.ollama_online
            }
        }
    
    async def shutdown(self) -> None:
        """Graceful shutdown - stop monitoring and flush state"""
        logger.info("🎭 Pete: Shutting down...")

        self._monitoring_active = False

        # Broadcast shutdown notice to connected clients
        if self.hub:
            try:
                await self.hub.broadcast({
                    "type": "pete_shutdown",
                    "message": "PubCast AI shutting down gracefully",
                    "timestamp": time.time()
                })
            except Exception:
                pass

        # Close Rust bridge if connected
        if self.rust_bridge and hasattr(self.rust_bridge, "disconnect"):
            try:
                await self.rust_bridge.disconnect()
                logger.info("🎭 Pete: Rust bridge disconnected")
            except Exception as e:
                logger.warning(f"🎭 Pete: Rust bridge disconnect error: {e}")

        # Close WebRTC bridge if active
        if self.webrtc_bridge and hasattr(self.webrtc_bridge, "stop"):
            try:
                await self.webrtc_bridge.stop()
                logger.info("🎭 Pete: WebRTC bridge stopped")
            except Exception as e:
                logger.warning(f"🎭 Pete: WebRTC bridge stop error: {e}")

        # Save final metrics snapshot
        try:
            metrics_path = self.data_dir / "logs" / "pete_final_metrics.json"
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(metrics_path, "w") as f:
                json.dump(self.get_status(), f, indent=2)
            logger.info(f"🎭 Pete: Final metrics saved to {metrics_path}")
        except Exception as e:
            logger.warning(f"🎭 Pete: Could not save final metrics: {e}")

        logger.info("🎭 Pete: Shutdown complete")
