#!/usr/bin/env python3
"""
Auto-Updater — checks for updates and applies them safely.
"""

import os
import time
import json
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger("autonomy.updater")


class AutoUpdater:
    """Automatically update bot code and dependencies."""

    def __init__(self, check_interval_hours: int = 6):
        self.check_interval = timedelta(hours=check_interval_hours)
        self.last_check: Optional[datetime] = None
        self.update_log: list = []

    def check_for_updates(self) -> Dict:
        """Check if updates are available."""
        try:
            # Fetch latest from GitHub
            result = subprocess.run(
                "cd /opt/bot && git fetch origin main",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Check if behind
            result = subprocess.run(
                "cd /opt/bot && git rev-list HEAD..origin/main --count",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            commits_behind = int(result.stdout.strip()) if result.returncode == 0 else 0

            return {
                "updates_available": commits_behind > 0,
                "commits_behind": commits_behind,
                "last_check": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error("Update check failed: %s", e)
            return {"updates_available": False, "error": str(e)}

    def apply_update(self) -> Dict:
        """Apply available updates safely."""
        logger.info("Applying updates...")

        steps = [
            ("backup", "cp -r /opt/bot /opt/backups/bot-$(date +%Y%m%d-%H%M%S)"),
            ("pull", "cd /opt/bot && git reset --hard origin/main"),
            ("build", "cd /opt/bot && docker-compose build --no-cache"),
            ("deploy", "cd /opt/bot && docker-compose up -d"),
            ("health", "sleep 10 && curl -f http://localhost:3000/api/health"),
        ]

        results = []
        for name, cmd in steps:
            logger.info("Update step: %s", name)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=300
            )

            step_result = {
                "step": name,
                "status": "success" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
            }
            results.append(step_result)

            if result.returncode != 0:
                logger.error("Update step failed: %s — %s", name, result.stderr)
                if name == "health":
                    # Rollback
                    logger.warning("Rolling back...")
                    subprocess.run(
                        "cd /opt/backups/bot-* && docker-compose up -d", shell=True
                    )
                break

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "results": results,
            "success": all(r["status"] == "success" for r in results),
        }
        self.update_log.append(record)
        return record

    def run(self):
        """Main update loop."""
        while True:
            now = datetime.utcnow()
            if self.last_check is None or now - self.last_check > self.check_interval:
                self.last_check = now
                status = self.check_for_updates()

                if status.get("updates_available"):
                    logger.info(
                        "Updates available: %d commits", status["commits_behind"]
                    )
                    self.apply_update()
                else:
                    logger.debug("No updates available")

            time.sleep(3600)  # Check every hour


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    updater = AutoUpdater()
    updater.run()
