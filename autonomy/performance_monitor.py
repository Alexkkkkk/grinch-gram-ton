#!/usr/bin/env python3
"""
Performance Monitor — tracks bot performance and auto-optimizes.
"""
import os
import time
import json
import logging
import psutil
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List

logger = logging.getLogger("autonomy.performance")


class PerformanceMonitor:
    """Monitor and optimize bot performance."""
    
    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self.metrics: deque = deque(maxlen=window_minutes * 60)
        self.alerts: List[Dict] = []
        self.optimizations_applied: List[Dict] = []
    
    def collect(self) -> Dict:
        """Collect current performance metrics."""
        metric = {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory": {
                "percent": psutil.virtual_memory().percent,
                "used_mb": psutil.virtual_memory().used // 1024 // 1024,
            },
            "disk": {
                "percent": psutil.disk_usage("/").percent,
            },
            "network": self._get_network_stats(),
            "processes": self._get_bot_processes(),
        }
        self.metrics.append(metric)
        return metric
    
    def _get_network_stats(self) -> Dict:
        """Get network I/O stats."""
        try:
            net = psutil.net_io_counters()
            return {
                "bytes_sent_mb": net.bytes_sent // 1024 // 1024,
                "bytes_recv_mb": net.bytes_recv // 1024 // 1024,
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
            }
        except:
            return {}
    
    def _get_bot_processes(self) -> List[Dict]:
        """Find GRINCH-GRAM processes."""
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            if "python" in proc.info.get("name", "").lower() or "grinch" in proc.info.get("name", "").lower():
                processes.append({
                    "pid": proc.info["pid"],
                    "cpu": proc.info.get("cpu_percent", 0),
                    "memory": proc.info.get("memory_percent", 0),
                })
        return processes
    
    def analyze(self) -> List[Dict]:
        """Analyze metrics and suggest optimizations."""
        if len(self.metrics) < 10:
            return []
        
        suggestions = []
        recent = list(self.metrics)[-60:]  # Last hour
        
        # CPU analysis
        avg_cpu = sum(m["cpu_percent"] for m in recent) / len(recent)
        if avg_cpu > 80:
            suggestions.append({
                "type": "cpu_high",
                "severity": "warning",
                "message": f"Average CPU {avg_cpu:.1f}% — consider reducing worker count",
                "action": "reduce_workers",
            })
        
        # Memory analysis
        avg_mem = sum(m["memory"]["percent"] for m in recent) / len(recent)
        if avg_mem > 85:
            suggestions.append({
                "type": "memory_high",
                "severity": "critical",
                "message": f"Average memory {avg_mem:.1f}% — restart recommended",
                "action": "restart_bot",
            })
        
        # Disk analysis
        latest = recent[-1]
        if latest["disk"]["percent"] > 90:
            suggestions.append({
                "type": "disk_full",
                "severity": "critical",
                "message": f"Disk {latest['disk']['percent']}% full — clear logs",
                "action": "clear_logs",
            })
        
        return suggestions
    
    def apply_optimization(self, suggestion: Dict) -> bool:
        """Apply an optimization suggestion."""
        action = suggestion.get("action")
        
        if action == "clear_logs":
            try:
                os.system("find /opt/bot/logs -name '*.log' -mtime +7 -delete")
                os.system("find /var/log -name '*.log' -mtime +30 -delete")
                self.optimizations_applied.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": action,
                    "status": "success",
                })
                return True
            except Exception as e:
                logger.error("Optimization failed: %s", e)
                return False
        
        elif action == "reduce_workers":
            # This would require config change and restart
            logger.info("Worker reduction suggested — manual review needed")
            return False
        
        return False
    
    def run(self, interval: int = 60):
        """Main monitoring loop."""
        logger.info("Performance monitor started")
        while True:
            try:
                self.collect()
                suggestions = self.analyze()
                for suggestion in suggestions:
                    logger.warning("Performance issue: %s", suggestion["message"])
                    if suggestion["severity"] == "critical":
                        self.apply_optimization(suggestion)
            except Exception as e:
                logger.exception("Performance monitor error: %s", e)
            time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitor = PerformanceMonitor()
    monitor.run()
