#!/usr/bin/env python3
"""
VPS Command Executor — safely executes commands on VPS and reports results.
"""

import logging
import re
import shlex
import subprocess
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("autonomy.executor")


class SafeExecutor:
    """Execute commands safely with validation and logging."""

    ALLOWED_COMMANDS = {
        "docker": ["ps", "logs", "restart", "stop", "start", "compose"],
        "git": ["status", "log", "pull", "fetch", "reset"],
        "systemctl": ["status", "restart", "start", "stop"],
        "python3": ["-m", "pytest", "-c"],
        "curl": ["-f", "-s", "-o"],
        "make": ["deploy", "test", "lint", "build"],
        "uptime": [],
        "free": ["-h"],
        "df": ["-h"],
    }

    def __init__(self):
        self.history: List[Dict] = []

    def validate(self, command: str) -> bool:
        """Validate if command is allowed."""
        parts = command.split()
        if not parts:
            return False

        base = parts[0]
        if base not in self.ALLOWED_COMMANDS:
            logger.warning("Command not allowed: %s", base)
            return False

        # Reject shell metacharacters outright: they are never needed now that
        # the command runs without a shell, and their presence signals a
        # crafted payload that would have been interpreted under `sh -c`.
        if re.search(r"[;&|`$><\n\r]", command):
            logger.error("Shell metacharacters blocked: %s", command)
            return False

        # Check for dangerous patterns
        dangerous = [
            "rm -rf /",
            "> /dev/sda",
            "mkfs",
            "dd if=/dev/zero",
            ":(){ :|:& };:",
        ]
        for pattern in dangerous:
            if pattern in command:
                logger.error("Dangerous command blocked: %s", command)
                return False

        return True

    def execute(self, command: str, timeout: int = 60, cwd: str = None) -> Dict:
        """Execute a validated command without a shell (no `sh -c`)."""
        if not self.validate(command):
            return {"status": "blocked", "command": command}

        argv = shlex.split(command)
        logger.info("Executing: %s", argv)

        try:
            result = subprocess.run(
                argv,
                shell=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            record = {
                "timestamp": datetime.utcnow().isoformat(),
                "command": command,
                "status": "success" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }

            self.history.append(record)
            return record

        except subprocess.TimeoutExpired:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "command": command,
                "status": "timeout",
            }
        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "command": command,
                "status": "error",
                "error": str(e),
            }

    def docker_health(self) -> Dict:
        """Check Docker health."""
        return self.execute(
            "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'"
        )

    def bot_logs(self, lines: int = 50) -> Dict:
        """Get bot logs."""
        return self.execute(
            f"docker compose logs --tail={int(lines)} bot", cwd="/opt/bot"
        )

    def system_info(self) -> Dict:
        """Get system information."""
        return {
            "status": "ok",
            "uptime": self.execute("uptime"),
            "memory": self.execute("free -h"),
            "disk": self.execute("df -h /"),
        }
