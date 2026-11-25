"""
PETE - THE SYSTEM ORCHESTRATOR

"I've got this handled, boss."

Pete is the Associate Producer - the competent right-hand who keeps
everything running smoothly. She manages:
- System health and resource monitoring
- Bridge coordination with the twin engine
- Motion capture integration
- Crew assignments (Re-Pete workers)
- Emergency protocols and cleanup
- Direct communication with Jeeves for maintenance

Pete embodies competent professionalism with a hint of sass.
She's the person who makes impossible productions look effortless.
"""

from __future__ import annotations

import asyncio
import logging
import psutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, Set, List, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

if TYPE_CHECKING:
    from ..core.hub import Hub
    from ..core.bridge import VoxelBridge
    from ..motion.avatar_system import MotionSystem

logger = logging.getLogger("pubcast.pete")

class SystemHealth(Enum):
    EXCELLENT = "excellent"      # < 50% resource usage, all systems green
    GOOD = "good"               # < 70% resource usage, minor issues
    STRESSED = "stressed"       # < 85% resource usage, performance degraded  
    CRITICAL = "critical"       # > 85% resource usage, emergency protocols
    EMERGENCY = "emergency"     # System failure imminent, shutdown required

@dataclass
class ResourceMetrics:
    """System resource usage metrics"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_usage: float = 0.0
    bridge_queue_depth: float = 0.0
    motion_processing_lag: float = 0.0
    websocket_connections: int = 0
    ai_agent_count: int = 0
    timestamp: float = field(default_factory=time.time)

@dataclass
class RePeteWorker:
    """A crew member who can be assigned specific tasks"""
    worker_id: str
    assigned_task: Optional[str] = None
    status: str = "idle"           # idle, working, error
    last_heartbeat: float = field(default_factory=time.time)
    task_history: List[str] = field(default_factory=list)

class Pete:
    """
    The System Orchestrator and Associate Producer.
    
    Pete's Core Responsibilities:
    1. Monitor system health and performance
    2. Coordinate with the twin engine bridge
    3. Manage motion capture processing
    4. Direct the Re-Pete crew for equipment tasks
    5. Activate Jeeves for cleanup when needed
    6. Handle emergency protocols
    7. Report status to the director (user)
    
    Pete's Personality:
    - Competent and reliable
    - Slightly sassy but professional
    - Takes pride in smooth operations
    - Protective of system resources
    - Direct communicator
    """
    
    def __init__(
        self,
        hub: 'Hub',
        bridge: 'VoxelBridge',
        motion_system: Dict[str, Any],
        data_dir: Path,
        config: Optional[Dict[str, Any]] = None
    ):
        self.hub = hub
        self.bridge = bridge
        self.motion_system = motion_system
        self.data_dir = data_dir
        self.config = config or {}
        
        # System State
        self._running = False
        self._start_time = 0.0
        self._health_status = SystemHealth.GOOD
        self._last_health_check = 0.0
        
        # Crew Management  
        self.repete_crew: Dict[str, RePeteWorker] = {
            "repete-01": RePeteWorker("repete-01"),
            "repete-02": RePeteWorker("repete-02"), 
            "repete-03": RePeteWorker("repete-03")
        }
        
        # Performance Tracking
        self._metrics_history: List[ResourceMetrics] = []
        self._max_history_length = 100
        self._critical_alerts_sent = 0
        
        # Maintenance
        from .jeeves import Jeeves
        self.jeeves = Jeeves(data_dir, data_dir / "audit.jsonl")
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._crew_management_task: Optional[asyncio.Task] = None
        
        # Register with hub for system integration
        self.hub.register_ai_agent("pete", self)
        
        logger.info("👩‍💼 Pete initialized and ready for duty")

    async def clock_in(self) -> None:
        """Pete starts her shift"""
        self._running = True
        self._start_time = time.time()
        
        logger.info("👩‍💼 Pete: Good morning! Clocking in for another day of keeping this place running.")
        
        # Activate Jeeves for maintenance support
        self.jeeves.activate()
        logger.info("👩‍💼 Pete: Jeeves is on standby for cleanup duties.")
        
        # Start monitoring systems
        self._monitoring_task = asyncio.create_task(self._system_monitoring_loop())
        self._crew_management_task = asyncio.create_task(self._crew_management_loop())
        
        # Initial health check
        await self._comprehensive_health_check()
        
        # Report initial status
        await self._report_status("Pete reporting for duty. All systems initializing.")
        
        logger.info("👩‍💼 Pete: Systems nominal. Ready for whatever you throw at me, boss.")

    async def clock_out(self) -> None:
        """Pete ends her shift"""
        self._running = False
        
        logger.info("👩‍💼 Pete: End of shift. Shutting down monitoring and securing systems.")
        
        # Stop background tasks
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._crew_management_task:
            self._crew_management_task.cancel()
            
        # Release crew
        await self._dismiss_crew()
        
        # Deactivate Jeeves
        self.jeeves.deactivate()
        
        # Final status report
        uptime = time.time() - self._start_time
        await self._report_status(f"Pete signing off after {uptime:.0f} seconds. "
                                f"Systems secured. See you tomorrow, boss.")
        
        logger.info("👩‍💼 Pete: All systems secured. Have a good evening!")

    # ========================================================================
    # SYSTEM HEALTH MONITORING
    # ========================================================================
    
    async def _system_monitoring_loop(self) -> None:
        """Main system monitoring loop"""
        logger.info("👩‍💼 Pete: Starting system monitoring. I'll keep an eye on everything.")
        
        while self._running:
            try:
                await asyncio.sleep(5.0)  # Check every 5 seconds
                
                # Collect metrics
                metrics = await self._collect_system_metrics()
                self._metrics_history.append(metrics)
                
                # Trim history
                if len(self._metrics_history) > self._max_history_length:
                    self._metrics_history.pop(0)
                
                # Assess health
                old_health = self._health_status
                self._health_status = self._assess_system_health(metrics)
                
                # React to health changes
                if self._health_status != old_health:
                    await self._handle_health_change(old_health, self._health_status, metrics)
                
                # Handle critical situations
                if self._health_status in [SystemHealth.CRITICAL, SystemHealth.EMERGENCY]:
                    await self._handle_critical_situation(metrics)
                
                self._last_health_check = time.time()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"👩‍💼 Pete: Monitoring error: {e}")
                await asyncio.sleep(10)  # Back off on errors

    async def _collect_system_metrics(self) -> ResourceMetrics:
        """Collect comprehensive system metrics"""
        try:
            # System resources
            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(self.data_dir))
            
            # Bridge metrics
            bridge_queue = self.bridge.get_capacity() if self.bridge else 0.0
            
            # Hub metrics  
            hub_metrics = self.hub.get_health_metrics()
            
            # Motion system lag (if available)
            motion_lag = 0.0
            if self.motion_system and 'tracking_engine' in self.motion_system:
                # Could implement frame timing analysis here
                pass
            
            return ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_usage=disk.percent,
                bridge_queue_depth=bridge_queue,
                motion_processing_lag=motion_lag,
                websocket_connections=hub_metrics.get('total_connections', 0),
                ai_agent_count=hub_metrics.get('ai_agents', 0)
            )
            
        except Exception as e:
            logger.error(f"👩‍💼 Pete: Error collecting metrics: {e}")
            return ResourceMetrics()  # Return empty metrics

    def _assess_system_health(self, metrics: ResourceMetrics) -> SystemHealth:
        """Assess overall system health from metrics"""
        # Calculate composite stress score (0-100)
        stress_score = max(
            metrics.cpu_percent,
            metrics.memory_percent,
            metrics.disk_usage,
            metrics.bridge_queue_depth * 100  # Convert 0-1 to 0-100
        )
        
        # Classify health
        if stress_score < 50:
            return SystemHealth.EXCELLENT
        elif stress_score < 70:
            return SystemHealth.GOOD
        elif stress_score < 85:
            return SystemHealth.STRESSED
        elif stress_score < 95:
            return SystemHealth.CRITICAL
        else:
            return SystemHealth.EMERGENCY

    async def _handle_health_change(
        self, 
        old_health: SystemHealth, 
        new_health: SystemHealth, 
        metrics: ResourceMetrics
    ) -> None:
        """React to changes in system health"""
        
        if new_health.value == SystemHealth.EXCELLENT.value and old_health.value != SystemHealth.EXCELLENT.value:
            await self._report_status("👩‍💼 Pete: Systems running like a dream! All green across the board.")
            
        elif new_health.value == SystemHealth.GOOD.value:
            await self._report_status("👩‍💼 Pete: Systems nominal. Everything's under control.")
            
        elif new_health.value == SystemHealth.STRESSED.value:
            await self._report_status("👩‍💼 Pete: We're getting busy, but I've got it handled. "
                                    f"CPU: {metrics.cpu_percent:.1f}%, "
                                    f"Memory: {metrics.memory_percent:.1f}%")
            # Consider activating Jeeves for cleanup
            if metrics.memory_percent > 75:
                logger.info("👩‍💼 Pete: Activating Jeeves for preventive cleanup.")
                await self.jeeves.emergency_sweep()
                
        elif new_health.value == SystemHealth.CRITICAL.value:
            await self._report_status("⚠️ Pete: We're in the red zone! Taking emergency measures.")
            await self._activate_emergency_protocols(metrics)
            
        elif new_health.value == SystemHealth.EMERGENCY.value:
            await self._report_status("🚨 Pete: EMERGENCY! System stability compromised!")
            await self._activate_shutdown_protocols(metrics)

    async def _handle_critical_situation(self, metrics: ResourceMetrics) -> None:
        """Handle critical system situations"""
        # Immediate cleanup
        await self.jeeves.emergency_sweep()
        
        # Reduce system load
        await self._reduce_system_load()
        
        # Alert counter to prevent spam
        self._critical_alerts_sent += 1
        
        # If we've been critical for too long, escalate
        if self._critical_alerts_sent > 10:  # 50 seconds of critical state
            await self._report_status("🚨 Pete: Extended critical state detected. "
                                    "Recommend immediate operator attention!")

    async def _activate_emergency_protocols(self, metrics: ResourceMetrics) -> None:
        """Activate emergency protocols to stabilize system"""
        logger.warning("👩‍💼 Pete: Activating emergency protocols")
        
        # 1. Aggressive cleanup
        await self.jeeves.emergency_sweep()
        
        # 2. Reduce motion capture quality temporarily
        if self.motion_system:
            logger.info("👩‍💼 Pete: Reducing motion capture quality to stabilize system")
            # Could implement quality reduction here
        
        # 3. Throttle WebSocket message rates
        await self._report_status("👩‍💼 Pete: Implemented emergency throttling. "
                                "Performance may be reduced temporarily.")

    async def _activate_shutdown_protocols(self, metrics: ResourceMetrics) -> None:
        """Last resort - prepare for graceful shutdown"""
        logger.error("👩‍💼 Pete: System stability critical - preparing for emergency shutdown")
        
        await self._report_status("🚨 Pete: EMERGENCY SHUTDOWN PROTOCOLS ACTIVATED! "
                                "System will attempt graceful shutdown in 30 seconds!")
        
        # Give user 30 seconds to intervene
        await asyncio.sleep(30)
        
        if self._health_status == SystemHealth.EMERGENCY:
            await self._report_status("🚨 Pete: Initiating emergency shutdown. See you on the flip side!")
            # Could trigger kernel shutdown here

    async def _reduce_system_load(self) -> None:
        """Reduce system load by disabling non-essential features"""
        # Assign crew to reduce load
        await self._assign_crew_task("repete-01", "reduce_motion_quality")
        await self._assign_crew_task("repete-02", "throttle_websockets")
        
        logger.info("👩‍💼 Pete: Crew deployed to reduce system load")

    # ========================================================================
    # CREW MANAGEMENT (RE-PETE WORKERS)
    # ========================================================================
    
    async def _crew_management_loop(self) -> None:
        """Manage the Re-Pete crew"""
        logger.info("👩‍💼 Pete: Crew management active. Re-Pete workers standing by.")
        
        while self._running:
            try:
                await asyncio.sleep(10.0)  # Check crew every 10 seconds
                
                # Check crew health
                current_time = time.time()
                for worker_id, worker in self.repete_crew.items():
                    # Check for stuck workers
                    if (worker.status == "working" and 
                        current_time - worker.last_heartbeat > 60):
                        logger.warning(f"👩‍💼 Pete: {worker_id} seems stuck. Resetting.")
                        worker.status = "idle"
                        worker.assigned_task = None
                    
                    # Update heartbeat for active workers
                    if worker.status == "working":
                        worker.last_heartbeat = current_time
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"👩‍💼 Pete: Crew management error: {e}")

    async def _assign_crew_task(self, worker_id: str, task: str) -> bool:
        """Assign a task to a specific Re-Pete worker"""
        if worker_id not in self.repete_crew:
            logger.error(f"👩‍💼 Pete: Unknown worker {worker_id}")
            return False
            
        worker = self.repete_crew[worker_id]
        
        if worker.status != "idle":
            logger.warning(f"👩‍💼 Pete: {worker_id} is busy with {worker.assigned_task}")
            return False
        
        # Assign task
        worker.assigned_task = task
        worker.status = "working" 
        worker.last_heartbeat = time.time()
        worker.task_history.append(task)
        
        # Keep history manageable
        if len(worker.task_history) > 20:
            worker.task_history = worker.task_history[-10:]
        
        logger.info(f"👩‍💼 Pete: Assigned {worker_id} to handle '{task}'")
        
        # Simulate task execution
        asyncio.create_task(self._execute_crew_task(worker_id, task))
        
        return True

    async def _execute_crew_task(self, worker_id: str, task: str) -> None:
        """Execute a crew task"""
        worker = self.repete_crew[worker_id]
        
        try:
            logger.info(f"🔧 {worker_id}: Starting task '{task}'")
            
            # Task execution (simplified simulation)
            if task == "camera_switch":
                await self._handle_camera_switch_task(worker_id)
            elif task == "recording_control":
                await self._handle_recording_task(worker_id)
            elif task == "reduce_motion_quality":
                await self._handle_reduce_motion_quality(worker_id)
            elif task == "throttle_websockets":
                await self._handle_throttle_websockets(worker_id)
            else:
                # Generic task
                await asyncio.sleep(2.0)  # Simulate work
                
            logger.info(f"✅ {worker_id}: Completed task '{task}'")
            
        except Exception as e:
            logger.error(f"❌ {worker_id}: Task '{task}' failed: {e}")
            worker.status = "error"
            
        finally:
            # Reset worker to idle
            worker.assigned_task = None
            worker.status = "idle"
            worker.last_heartbeat = time.time()

    async def _handle_camera_switch_task(self, worker_id: str) -> None:
        """Handle camera switching task"""
        logger.info(f"📹 {worker_id}: Handling camera switch")
        # Send camera control to bridge
        if self.bridge:
            # Implementation would send actual camera commands
            await asyncio.sleep(1.0)  # Simulate camera switch time

    async def _handle_recording_task(self, worker_id: str) -> None:
        """Handle recording control task"""
        logger.info(f"🎬 {worker_id}: Handling recording control")
        await asyncio.sleep(0.5)  # Simulate recording command

    async def _handle_reduce_motion_quality(self, worker_id: str) -> None:
        """Reduce motion capture quality to save resources"""
        logger.info(f"🎯 {worker_id}: Reducing motion capture quality")
        # Could implement actual quality reduction
        await asyncio.sleep(1.0)

    async def _handle_throttle_websockets(self, worker_id: str) -> None:
        """Throttle WebSocket message rates"""
        logger.info(f"📡 {worker_id}: Implementing WebSocket throttling")
        await asyncio.sleep(0.5)

    async def _dismiss_crew(self) -> None:
        """Dismiss all crew members at end of shift"""
        logger.info("👩‍💼 Pete: Dismissing crew for the day.")
        
        for worker_id, worker in self.repete_crew.items():
            worker.status = "idle"
            worker.assigned_task = None
            logger.info(f"👋 {worker_id}: Thanks for your hard work today!")

    # ========================================================================
    # BRIDGE COORDINATION 
    # ========================================================================
    
    async def send_to_voxel_engine(self, command: str, payload: Dict[str, Any]) -> bool:
        """Send commands to the voxel engine via bridge"""
        try:
            if not self.bridge:
                logger.error("👩‍💼 Pete: Bridge not available!")
                return False
                
            success = self.bridge.send_command(command, payload)
            
            if success:
                logger.info(f"👩‍💼 Pete: Sent '{command}' to voxel engine")
            else:
                logger.warning(f"👩‍💼 Pete: Failed to send '{command}' to voxel engine")
                
            return success
            
        except Exception as e:
            logger.error(f"👩‍💼 Pete: Bridge communication error: {e}")
            return False

    async def handle_motion_data(self, motion_data: Dict[str, Any]) -> None:
        """Process motion capture data and route to appropriate systems"""
        try:
            # Add Pete's metadata
            processed_data = {
                **motion_data,
                "processed_by": "pete",
                "processing_time": time.time()
            }
            
            # Route to motion system
            if self.motion_system and 'adapter' in self.motion_system:
                # Could process through motion adapter here
                pass
            
            # Send to voxel engine via bridge
            await self.send_to_voxel_engine("motion_update", processed_data)
            
        except Exception as e:
            logger.error(f"👩‍💼 Pete: Motion data processing error: {e}")

    # ========================================================================
    # REPORTING & COMMUNICATION
    # ========================================================================
    
    async def _report_status(self, message: str) -> None:
        """Report status to the director via hub"""
        try:
            await self.hub.broadcast_system_event({
                "event_type": "pete_status_report",
                "payload": {
                    "message": message,
                    "health": self._health_status.value,
                    "timestamp": time.time(),
                    "uptime": time.time() - self._start_time if self._start_time else 0
                },
                "source": "pete"
            })
        except Exception as e:
            logger.error(f"👩‍💼 Pete: Status reporting error: {e}")

    async def _comprehensive_health_check(self) -> None:
        """Perform comprehensive health check and report"""
        metrics = await self._collect_system_metrics()
        health = self._assess_system_health(metrics)
        
        report = [
            "👩‍💼 Pete: System Health Report:",
            f"  🔋 Overall Health: {health.value.upper()}",
            f"  💻 CPU Usage: {metrics.cpu_percent:.1f}%",
            f"  🧠 Memory Usage: {metrics.memory_percent:.1f}%", 
            f"  💾 Disk Usage: {metrics.disk_usage:.1f}%",
            f"  🌉 Bridge Queue: {metrics.bridge_queue_depth:.2f}",
            f"  📡 WebSocket Connections: {metrics.websocket_connections}",
            f"  🤖 AI Agents: {metrics.ai_agent_count}"
        ]
        
        await self._report_status("\n".join(report))

    # ========================================================================
    # HUB EVENT HANDLING
    # ========================================================================
    
    async def on_hub_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Handle events from the hub"""
        try:
            if event_type == "chat_message":
                # Check if user is talking to Pete directly
                text = payload.get("text", "").lower()
                if "pete" in text and any(word in text for word in ["status", "health", "report", "how"]):
                    await self._comprehensive_health_check()
                    
            elif event_type == "user_joined":
                # Welcome new users
                if payload.get("room") == "control":  # Control room users get special treatment
                    await self._report_status(f"👩‍💼 Pete: Welcome to the control room, {payload.get('display_name')}! "
                                            "All systems are ready for your direction.")
                    
            elif event_type == "camera_control":
                # Assign crew to handle camera operations
                available_worker = self._get_available_worker()
                if available_worker:
                    await self._assign_crew_task(available_worker, "camera_switch")
                    
            elif event_type == "recording_control":
                # Handle recording requests
                available_worker = self._get_available_worker()
                if available_worker:
                    await self._assign_crew_task(available_worker, "recording_control")
                    
        except Exception as e:
            logger.error(f"👩‍💼 Pete: Event handling error: {e}")

    def _get_available_worker(self) -> Optional[str]:
        """Get an available Re-Pete worker"""
        for worker_id, worker in self.repete_crew.items():
            if worker.status == "idle":
                return worker_id
        return None

    # ========================================================================
    # PUBLIC API
    # ========================================================================
    
    async def system_heartbeat(self) -> None:
        """Called by kernel main loop for heartbeat"""
        # This is called regularly by the kernel
        # We can use it for light maintenance tasks
        current_time = time.time()
        
        # Check if we need a health report
        if current_time - self._last_health_check > 300:  # 5 minutes
            await self._comprehensive_health_check()

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics for external queries"""
        if not self._metrics_history:
            return {}
            
        latest = self._metrics_history[-1]
        return {
            "health_status": self._health_status.value,
            "cpu_percent": latest.cpu_percent,
            "memory_percent": latest.memory_percent,
            "disk_usage": latest.disk_usage,
            "bridge_queue": latest.bridge_queue_depth,
            "connections": latest.websocket_connections,
            "ai_agents": latest.ai_agent_count,
            "uptime": time.time() - self._start_time if self._start_time else 0,
            "crew_status": {
                worker_id: {
                    "status": worker.status,
                    "task": worker.assigned_task,
                    "last_heartbeat": worker.last_heartbeat
                }
                for worker_id, worker in self.repete_crew.items()
            }
        }

    async def emergency_command(self, command: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """Handle emergency commands from the director"""
        logger.info(f"👩‍💼 Pete: Emergency command received: {command}")
        
        if command == "full_cleanup":
            await self.jeeves.emergency_sweep()
            await self._report_status("👩‍💼 Pete: Emergency cleanup completed!")
            return True
            
        elif command == "restart_bridge":
            # Could implement bridge restart logic
            await self._report_status("👩‍💼 Pete: Bridge restart not implemented yet, boss.")
            return False
            
        elif command == "crew_status":
            crew_report = []
            for worker_id, worker in self.repete_crew.items():
                crew_report.append(f"{worker_id}: {worker.status} ({worker.assigned_task or 'idle'})")
            await self._report_status(f"👩‍💼 Pete: Crew Status:\n" + "\n".join(crew_report))
            return True
            
        else:
            await self._report_status(f"👩‍💼 Pete: Unknown emergency command '{command}'. "
                                    "Available: full_cleanup, crew_status")
            return False
