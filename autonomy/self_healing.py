#!/usr/bin/env python3
"""
Self-Healing Engine — automatically fixes common problems on VPS.
Runs as daemon, monitors system health, applies fixes without human intervention.
"""
import os
import sys
import time
import json
import signal
import logging
import subprocess
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("autonomy.self_healing")


class SelfHealingEngine:
    """Autonomous healing for GRINCH-GRAM bot."""
    
    HEALING_ACTIONS = {
        "restart_bot": {
            "description": "Restart Docker containers",
            "command": "cd /opt/bot && docker-compose restart bot",
            "risk": "low",
        },
        "rebuild_bot": {
            "description": "Rebuild and restart bot",
            "command": "cd /opt/bot && docker-compose down && docker-compose up -d --build",
            "risk": "medium",
        },
        "clear_cache": {
            "description": "Clear Python cache and temp files",
            "command": "find /opt/bot -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; find /tmp -name '*.tmp' -delete 2>/dev/null",
            "risk": "low",
        },
        "free_memory": {
            "description": "Free system memory",
            "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
            "risk": "low",
        },
        "restart_nginx": {
            "description": "Restart nginx container",
            "command": "cd /opt/bot && docker-compose restart nginx",
            "risk": "low",
        },
        "update_code": {
            "description": "Pull latest code from GitHub",
            "command": "cd /opt/bot && git fetch origin && git reset --hard origin/main && docker-compose up -d --build",
            "risk": "medium",
        },
        "fix_permissions": {
            "description": "Fix file permissions",
            "command": "chown -R grinch:grinch /opt/bot && chmod -R 755 /opt/bot/scripts",
            "risk": "low",
        },
        "backup_and_reset_db": {
            "description": "Backup and reset SQLite DB if corrupted",
            "command": "cp /opt/bot/data/*.db /opt/backups/ 2>/dev/null; rm -f /opt/bot/data/*.db-wal /opt/bot/data/*.db-shm",
            "risk": "high",
        },
    }
    
    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.running = False
        self.healing_log: List[Dict] = []
        self.last_heal_time: Dict[str, datetime] = {}
        self.heal_cooldown = timedelta(minutes=5)
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)
    
    def _shutdown(self, signum, frame):
        logger.info("Self-healing engine shutting down...")
        self.running = False
    
    def check_bot_health(self) -> Dict:
        """Check if bot is healthy."""
        health = {"status": "unknown", "checks": {}}
        
        # Check Docker container
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=grinch-bot", "--format", "{{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            health["checks"]["docker"] = "running" if "Up" in result.stdout else "down"
        except Exception as e:
            health["checks"]["docker"] = f"error: {e}"
        
        # Check HTTP endpoint
        try:
            import requests
            resp = requests.get("http://localhost:3000/api/health", timeout=5)
            health["checks"]["http"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
        except Exception as e:
            health["checks"]["http"] = f"error: {e}"
        
        # Check memory
        mem = psutil.virtual_memory()
        health["checks"]["memory"] = {
            "percent": mem.percent,
            "available_mb": mem.available // 1024 // 1024,
        }
        
        # Check disk
        disk = psutil.disk_usage("/")
        health["checks"]["disk"] = {
            "percent": disk.percent,
            "free_gb": disk.free // 1024 // 1024 // 1024,
        }
        
        # Check CPU
        health["checks"]["cpu"] = {
            "percent": psutil.cpu_percent(interval=1),
        }
        
        # Determine overall status
        if health["checks"].get("docker") == "running" and health["checks"].get("http") == "ok":
            if mem.percent > 90 or disk.percent > 95:
                health["status"] = "degraded"
            else:
                health["status"] = "healthy"
        else:
            health["status"] = "critical"
        
        return health
    
    def heal(self, health: Dict) -> List[Dict]:
        """Apply healing actions based on health status."""
        actions_taken = []
        now = datetime.utcnow()
        
        if health["status"] == "healthy":
            return actions_taken
        
        # Critical: bot is down
        if health["status"] == "critical":
            if self._can_heal("restart_bot", now):
                result = self._execute_heal("restart_bot")
                actions_taken.append(result)
                time.sleep(10)
                
                # Check again
                new_health = self.check_bot_health()
                if new_health["status"] == "critical" and self._can_heal("rebuild_bot", now):
                    result = self._execute_heal("rebuild_bot")
                    actions_taken.append(result)
        
        # Degraded: resource issues
        elif health["status"] == "degraded":
            mem = health["checks"].get("memory", {})
            disk = health["checks"].get("disk", {})
            
            if mem.get("percent", 0) > 90 and self._can_heal("free_memory", now):
                actions_taken.append(self._execute_heal("free_memory"))
            
            if disk.get("percent", 0) > 95 and self._can_heal("clear_cache", now):
                actions_taken.append(self._execute_heal("clear_cache"))
            
            if self._can_heal("restart_bot", now):
                actions_taken.append(self._execute_heal("restart_bot"))
        
        return actions_taken
    
    def _can_heal(self, action: str, now: datetime) -> bool:
        """Check if enough time has passed since last heal."""
        last = self.last_heal_time.get(action)
        if last is None:
            return True
        return now - last > self.heal_cooldown
    
    def _execute_heal(self, action_name: str) -> Dict:
        """Execute a healing action."""
        action = self.HEALING_ACTIONS.get(action_name)
        if not action:
            return {"action": action_name, "status": "unknown", "error": "Action not found"}
        
        now = datetime.utcnow()
        self.last_heal_time[action_name] = now
        
        logger.warning("Executing heal: %s — %s", action_name, action["description"])
        
        try:
            result = subprocess.run(
                action["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            heal_record = {
                "timestamp": now.isoformat(),
                "action": action_name,
                "description": action["description"],
                "risk": action["risk"],
                "status": "success" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout[-500:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }
            
            self.healing_log.append(heal_record)
            
            if result.returncode != 0:
                logger.error("Heal failed: %s — %s", action_name, result.stderr)
            else:
                logger.info("Heal succeeded: %s", action_name)
            
            return heal_record
            
        except subprocess.TimeoutExpired:
            logger.error("Heal timeout: %s", action_name)
            return {
                "timestamp": now.isoformat(),
                "action": action_name,
                "status": "timeout",
            }
        except Exception as e:
            logger.error("Heal error: %s — %s", action_name, e)
            return {
                "timestamp": now.isoformat(),
                "action": action_name,
                "status": "error",
                "error": str(e),
            }
    
    def run(self):
        """Main healing loop."""
        logger.info("Self-healing engine started (interval=%ds)", self.check_interval)
        self.running = True
        
        while self.running:
            try:
                health = self.check_bot_health()
                logger.debug("Health status: %s", health["status"])
                
                if health["status"] != "healthy":
                    actions = self.heal(health)
                    for action in actions:
                        logger.info("Healing action: %s — %s", action["action"], action["status"])
                
                # Save healing log periodically
                if len(self.healing_log) > 0 and len(self.healing_log) % 10 == 0:
                    self._save_log()
                
            except Exception as e:
                logger.exception("Self-healing loop error: %s", e)
            
            time.sleep(self.check_interval)
        
        self._save_log()
        logger.info("Self-healing engine stopped")
    
    def _save_log(self):
        """Save healing log to disk."""
        path = "/app/data/healing_log.json"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.healing_log[-100:], f, indent=2, default=str)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    engine = SelfHealingEngine(check_interval=30)
    engine.run()
