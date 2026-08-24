#!/usr/bin/env python3
"""
GRINCH-GRAM Supervisor — orchestrates all autonomy modules.
Single entry point for self-healing, monitoring, updating.
"""
import os
import sys
import time
import signal
import logging
import threading
from pathlib import Path

# Add project root to path
sys.path.insert(0, "/opt/bot")

from autonomy.self_healing import SelfHealingEngine
from autonomy.performance_monitor import PerformanceMonitor
from autonomy.auto_updater import AutoUpdater

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/grinch/supervisor.log"),
    ],
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
        logger.info("=== GRINCH-GRAM Supervisor v3.1 Starting ===")
        self.running = True
        
        # Create log directory
        os.makedirs("/var/log/grinch", exist_ok=True)
        
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
