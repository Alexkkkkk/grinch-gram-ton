"""Conservative Git/Docker updater used by the optional VPS supervisor."""

from __future__ import annotations

import logging
import os
import subprocess
import time

logger = logging.getLogger("autonomy.auto_updater")


class AutoUpdater:
    """Check the configured branch and rebuild only when it changed."""

    def __init__(
        self,
        check_interval_hours: float = 6,
        project_dir: str | None = None,
    ):
        self.check_interval_hours = max(float(check_interval_hours), 0.01)
        self.project_dir = project_dir or os.getenv("BOT_DIR", "/opt/bot")
        self.running = False

    def _run(self, *command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    def check_for_updates(self) -> bool:
        """Fetch origin/main and deploy it when the commit changed.

        Returns ``True`` only after a successful rebuild and restart.
        """
        fetch = self._run("git", "fetch", "origin", "main", "--depth", "1")
        if fetch.returncode != 0:
            logger.error("Could not fetch updates: %s", fetch.stderr.strip())
            return False

        local = self._run("git", "rev-parse", "HEAD")
        remote = self._run("git", "rev-parse", "origin/main")
        if local.returncode != 0 or remote.returncode != 0:
            logger.error("Could not resolve local or remote commit")
            return False
        if local.stdout.strip() == remote.stdout.strip():
            logger.info("Code is up to date")
            return False

        pull = self._run("git", "reset", "--hard", "origin/main")
        if pull.returncode != 0:
            logger.error("Could not update working tree: %s", pull.stderr.strip())
            return False

        deploy = self._run("docker", "compose", "up", "-d", "--build", "bot")
        if deploy.returncode != 0:
            logger.error("Could not rebuild bot: %s", deploy.stderr.strip())
            return False

        logger.info("Updated bot to %s", remote.stdout.strip())
        return True

    def run(self) -> None:
        """Poll for updates until stopped."""
        self.running = True
        interval = self.check_interval_hours * 3600
        while self.running:
            try:
                self.check_for_updates()
            except Exception:
                logger.exception("Auto-update check failed")
            time.sleep(interval)

    def stop(self) -> None:
        self.running = False
