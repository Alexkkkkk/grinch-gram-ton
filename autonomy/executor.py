#!/usr/bin/env python3
"""
VPS Command Executor — safely executes commands on VPS and reports results.
"""

import logging
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

    def execute(self, command: str, timeout: int = 60) -> Dict:
        """Execute a validated command."""
        if not self.validate(command):
            return {"status": "blocked", "command": command}

        logger.info("Executing: %s", command)

        try:
            result = subprocess.run(
                command,
                shell=True,
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
        return self.execute(f"cd /opt/bot && docker-compose logs --tail={lines} bot")

    def system_info(self) -> Dict:
        """Get system information."""
        return self.execute("uptime && free -h && df -h /")
