"""
PETE - Technical Director AI
"The Master of Systems and Engineering Precision"

Responsibility:
    Monitor and manage all technical aspects of the PubCast AI platform.
    Coordinate between systems, handle errors, and ensure perfect operation.
    The technical genius who keeps everything running smoothly.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
import json

logger = logging.getLogger("pubcast.pete")

class PeteState(Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    MONITORING = "monitoring"
    EMERGENCY = "emergency"
    SHUTDOWN = "shutdown"

@dataclass
class SystemMetrics:
    """System performance metrics that Pete monitors"""
    timestamp: float
    cpu_usage: float
    memory_usage: float
    bridge_status: str
    active_connections: int
    error_count: int
    uptime: float

@dataclass 
class TechnicalIssue:
    """Technical issues that Pete tracks and resolves"""
    timestamp: float
    component: str
    severity: str  # "info", "warning", "error", "critical"
    message: str
    resolved: bool = False
    resolution_notes: Optional[str] = None

class Pete:
    """
    Pete - The Technical Director AI
    
    Pete is the master systems engineer who monitors every aspect of the
    PubCast AI platform. She handles technical coordination, error recovery,
    system optimization, and ensures broadcast-quality reliability.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.state = PeteState.INITIALIZING
        self.start_time = time.time()
        
        # System monitoring
        self.metrics_history: List[SystemMetrics] = []
        self.active_issues: Dict[str, TechnicalIssue] = {}
        self.resolved_issues: List[TechnicalIssue] = []
        
        # Component references (set during initialization)
        self.bridge = None
        self.hub = None
        self.recording_system = None
        self.camera_manager = None
        self.motion_system = None
        
        # Configuration
        self.monitoring_interval = 5.0  # seconds
        self.metrics_retention = 1000  # keep last 1000 metrics
        self.alert_thresholds = {
            "cpu_usage": 80.0,
            "memory_usage": 85.0,
            "error_rate": 5.0,
            "bridge_latency": 10.0  # milliseconds
        }
        
        logger.info("🔧 Pete initialized - Technical Director ready")
    
    async def initialize(self, components: Dict[str, Any]) -> bool:
        """Initialize Pete with system components"""
        try:
            self.bridge = components.get("bridge")
            self.hub = components.get("hub")
            self.recording_system = components.get("recording_system")
            self.camera_manager = components.get("camera_manager")
            self.motion_system = components.get("motion_system")
            
            self.state = PeteState.READY
            logger.info("✅ Pete initialization complete - All systems online")
            
            # Start monitoring loop
            asyncio.create_task(self._monitoring_loop())
            
            return True
            
        except Exception as e:
            logger.error(f"💥 Pete initialization failed: {e}")
            self.state = PeteState.EMERGENCY
            return False
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop - Pete's watchful eye"""
        self.state = PeteState.MONITORING
        
        while self.state == PeteState.MONITORING:
            try:
                # Collect system metrics
                metrics = await self._collect_metrics()
                self.metrics_history.append(metrics)
                
                # Trim history if needed
                if len(self.metrics_history) > self.metrics_retention:
                    self.metrics_history.pop(0)
                
                # Check for issues
                await self._analyze_metrics(metrics)
                
                # Broadcast status if needed
                if self.hub:
                    await self._broadcast_status()
                
                # Wait for next monitoring cycle
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"⚠️ Pete monitoring error: {e}")
                await asyncio.sleep(1.0)  # Brief pause before retry
    
    async def _collect_metrics(self) -> SystemMetrics:
        """Collect current system metrics"""
        import psutil
        
        # Basic system metrics
        cpu_usage = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        
        # Bridge status
        bridge_status = "unknown"
        if self.bridge:
            bridge_status = self.bridge.get_status().value if hasattr(self.bridge, 'get_status') else "active"
        
        # Connection count
        active_connections = 0
        if self.hub and hasattr(self.hub, 'get_connection_count'):
            active_connections = self.hub.get_connection_count()
        
        # Error tracking
        error_count = len([issue for issue in self.active_issues.values() 
                          if issue.severity in ["error", "critical"]])
        
        # Uptime
        uptime = time.time() - self.start_time
        
        return SystemMetrics(
            timestamp=time.time(),
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            bridge_status=bridge_status,
            active_connections=active_connections,
            error_count=error_count,
            uptime=uptime
        )
    
    async def _analyze_metrics(self, metrics: SystemMetrics) -> None:
        """Analyze metrics and detect issues"""
        # CPU usage check
        if metrics.cpu_usage > self.alert_thresholds["cpu_usage"]:
            await self._report_issue(
                "system", "warning",
                f"High CPU usage: {metrics.cpu_usage:.1f}%"
            )
        
        # Memory usage check  
        if metrics.memory_usage > self.alert_thresholds["memory_usage"]:
            await self._report_issue(
                "system", "warning",
                f"High memory usage: {metrics.memory_usage:.1f}%"
            )
        
        # Bridge status check
        if metrics.bridge_status not in ["active", "ready", "connected"]:
            await self._report_issue(
                "bridge", "error",
                f"Bridge status: {metrics.bridge_status}"
            )
    
    async def _report_issue(self, component: str, severity: str, message: str) -> None:
        """Report and track a technical issue"""
        issue_key = f"{component}_{severity}_{hash(message) % 10000}"
        
        # Don't spam duplicate issues
        if issue_key in self.active_issues:
            return
        
        issue = TechnicalIssue(
            timestamp=time.time(),
            component=component,
            severity=severity,
            message=message
        )
        
        self.active_issues[issue_key] = issue
        
        logger.log(
            getattr(logging, severity.upper(), logging.INFO),
            f"🔧 Pete detected issue [{component}]: {message}"
        )
        
        # Attempt automatic resolution for known issues
        await self._attempt_auto_resolution(issue_key, issue)
    
    async def _attempt_auto_resolution(self, issue_key: str, issue: TechnicalIssue) -> None:
        """Attempt to automatically resolve known issues"""
        resolved = False
        resolution_notes = None
        
        try:
            # Bridge reconnection
            if issue.component == "bridge" and self.bridge:
                if hasattr(self.bridge, 'reconnect'):
                    await self.bridge.reconnect()
                    resolved = True
                    resolution_notes = "Attempted bridge reconnection"
            
            # Memory cleanup
            elif "memory" in issue.message.lower():
                import gc
                gc.collect()
                resolved = True
                resolution_notes = "Triggered garbage collection"
            
            if resolved:
                issue.resolved = True
                issue.resolution_notes = resolution_notes
                
                # Move to resolved issues
                self.resolved_issues.append(issue)
                del self.active_issues[issue_key]
                
                logger.info(f"✅ Pete resolved issue: {resolution_notes}")
                
        except Exception as e:
            logger.error(f"⚠️ Pete auto-resolution failed: {e}")
    
    async def _broadcast_status(self) -> None:
        """Broadcast Pete's status to the hub"""
        if not self.hub:
            return
        
        try:
            status = {
                "type": "pete_status",
                "state": self.state.value,
                "uptime": time.time() - self.start_time,
                "active_issues": len(self.active_issues),
                "last_metrics": self.metrics_history[-1].__dict__ if self.metrics_history else None
            }
            
            if hasattr(self.hub, 'broadcast'):
                await self.hub.broadcast("pete_status", status)
                
        except Exception as e:
            logger.error(f"⚠️ Pete status broadcast failed: {e}")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        latest_metrics = self.metrics_history[-1] if self.metrics_history else None
        
        return {
            "pete_state": self.state.value,
            "uptime": time.time() - self.start_time,
            "latest_metrics": latest_metrics.__dict__ if latest_metrics else None,
            "active_issues": [
                {
                    "component": issue.component,
                    "severity": issue.severity,
                    "message": issue.message,
                    "timestamp": issue.timestamp
                }
                for issue in self.active_issues.values()
            ],
            "resolved_issues_count": len(self.resolved_issues),
            "components": {
                "bridge": self.bridge is not None,
                "hub": self.hub is not None,
                "recording": self.recording_system is not None,
                "cameras": self.camera_manager is not None,
                "motion": self.motion_system is not None
            }
        }
    
    async def emergency_shutdown(self) -> None:
        """Emergency shutdown procedure"""
        logger.warning("🚨 Pete initiating emergency shutdown")
        self.state = PeteState.EMERGENCY
        
        # Attempt to save critical data
        try:
            await self._save_emergency_state()
        except Exception as e:
            logger.error(f"💥 Emergency state save failed: {e}")
        
        # Signal other components
        if self.hub and hasattr(self.hub, 'broadcast'):
            await self.hub.broadcast("emergency_shutdown", {
                "source": "pete",
                "timestamp": time.time(),
                "reason": "Emergency shutdown initiated"
            })
    
    async def _save_emergency_state(self) -> None:
        """Save critical state during emergency"""
        emergency_data = {
            "timestamp": time.time(),
            "state": self.state.value,
            "active_issues": [issue.__dict__ for issue in self.active_issues.values()],
            "recent_metrics": [m.__dict__ for m in self.metrics_history[-10:]]
        }
        
        emergency_file = self.data_dir / "emergency_state.json"
        emergency_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(emergency_file, 'w') as f:
            json.dump(emergency_data, f, indent=2)
        
        logger.info(f"💾 Emergency state saved to {emergency_file}")
    
    async def graceful_shutdown(self) -> None:
        """Graceful shutdown procedure"""
        logger.info("🔧 Pete initiating graceful shutdown")
        self.state = PeteState.SHUTDOWN
        
        # Final status broadcast
        if self.hub:
            await self._broadcast_status()
        
        logger.info("✅ Pete shutdown complete")
