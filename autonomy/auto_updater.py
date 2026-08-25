#!/usr/bin/env python3
"""Auto-Updater v2 — checks for updates safely without shell execution.
Disabled by default in production; requires explicit env var to enable.
"""

import logging
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("autonomy.updater")

AUTO_UPDATE_ENABLED = __import__("os").getenv("AUTO_UPDATE_ENABLED", "").lower() in ("1", "true", "yes")


class AutoUpdater:
    def __init__(self, check_interval_hours: int = 6, repo_path: str = "/opt/bot"):
        self.check_interval = timedelta(hours=check_interval_hours)
        self.last_check: Optional[datetime] = None
        self.update_log: list = []
        self.repo_path = Path(repo_path)

    def _git_cmd(self, *args, cwd=None, timeout: int = 30):
        work_dir = cwd or self.repo_path
        return subprocess.run(
            ["git", *args], cwd=str(work_dir), capture_output=True,
            text=True, timeout=timeout, shell=False,
        )

    def check_for_updates(self) -> Dict:
        if not AUTO_UPDATE_ENABLED:
            return {"updates_available": False, "reason": "AUTO_UPDATE_ENABLED not set"}
        try:
            self._git_cmd("fetch", "origin", "main")
            result = self._git_cmd("rev-list", "HEAD..origin/main", "--count")
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
        if not AUTO_UPDATE_ENABLED:
            return {"success": False, "error": "AUTO_UPDATE_ENABLED not set"}
        logger.info("Applying updates...")
        backup_dir = self.repo_path.parent / f"backups/bot-{datetime.utcnow():%Y%m%d-%H%M%S}"
        steps = []
        try:
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copytree(self.repo_path, backup_dir)
            steps.append({"step": "backup", "status": "success"})
        except Exception as e:
            steps.append({"step": "backup", "status": "failed", "error": str(e)})
            return {"timestamp": datetime.utcnow().isoformat(), "results": steps, "success": False}

        result = self._git_cmd("reset", "--hard", "origin/main", timeout=60)
        steps.append({"step": "pull", "status": "success" if result.returncode == 0 else "failed", "returncode": result.returncode})
        if result.returncode != 0:
            return {"timestamp": datetime.utcnow().isoformat(), "results": steps, "success": False}

        compose_file = self.repo_path / "docker-compose.yml"
        if compose_file.exists():
            for name, args in [
                ("build", ["docker-compose", "build", "--no-cache"]),
                ("deploy", ["docker-compose", "up", "-d"]),
            ]:
                result = subprocess.run(args, cwd=str(self.repo_path), capture_output=True, text=True, timeout=300, shell=False)
                steps.append({"step": name, "status": "success" if result.returncode == 0 else "failed", "returncode": result.returncode})
                if result.returncode != 0:
                    logger.error("Update step failed: %s", name)
                    break

        record = {"timestamp": datetime.utcnow().isoformat(), "results": steps, "success": all(r["status"] == "success" for r in steps)}
        self.update_log.append(record)
        return record

    def run(self):
        while True:
            now = datetime.utcnow()
            if self.last_check is None or now - self.last_check > self.check_interval:
                self.last_check = now
                status = self.check_for_updates()
                if status.get("updates_available"):
                    logger.info("Updates available: %d commits", status["commits_behind"])
                    self.apply_update()
            time.sleep(3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    updater = AutoUpdater()
    updater.run()
