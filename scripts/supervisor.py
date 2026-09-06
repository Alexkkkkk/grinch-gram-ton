#!/usr/bin/env python3
"""
AI-Trading Supervisor — orchestrates all autonomy modules.
Single entry point for self-healing, monitoring, updating.
"""

import logging
import os
import signal
import sys
import threading
import time

# Add project root to path
sys.path.insert(0, "/opt/bot")

# The imports intentionally follow the path setup for direct script execution.
# isort: off
from autonomy.auto_updater import AutoUpdater
from autonomy.performance_monitor import PerformanceMonitor
from autonomy.self_healing import SelfHealingEngine

# isort: on

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("supervisor")


class Supervisor:
    """Orchestrates all autonomy services."""

    def __init__(self):
        self.running = False
        self.threads: list = []
        self.modules: dict = {}

        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info("Supervisor shutting down...")
        self.running = False

    def start(self):
        """Start all autonomy modules."""
        logger.info("=== AI-Trading Supervisor v3.1 Starting ===")
        self.running = True

        # Create log directory
        log_dir = os.getenv("GRINCH_LOG_DIR", "/var/log/grinch")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            logger.warning("Could not create log directory %s", log_dir)

        # Start self-healing
        healing = SelfHealingEngine(check_interval=30)
        t1 = threading.Thread(target=healing.run, daemon=True)
        t1.start()
        self.threads.append(t1)
        self.modules["healing"] = healing
        logger.info("Self-healing: STARTED")

        # Start performance monitor
        monitor = PerformanceMonitor()
        t2 = threading.Thread(target=monitor.run, args=(60,), daemon=True)
        t2.start()
        self.threads.append(t2)
        self.modules["performance"] = monitor
        logger.info("Performance monitor: STARTED")

        # Start auto-updater
        updater = AutoUpdater(check_interval_hours=6)
        t3 = threading.Thread(target=updater.run, daemon=True)
        t3.start()
        self.threads.append(t3)
        self.modules["updater"] = updater
        logger.info("Auto-updater: STARTED")

        logger.info("=== All modules running ===")

        # Keep main thread alive
        while self.running:
            time.sleep(1)

        logger.info("=== Supervisor stopped ===")


if __name__ == "__main__":
    supervisor = Supervisor()
    supervisor.start()
