"""Lightweight process and host performance monitor."""

from __future__ import annotations

import logging
import time
from typing import Any

import psutil

logger = logging.getLogger("autonomy.performance_monitor")


class PerformanceMonitor:
    """Collect bounded performance snapshots for supervisor logs."""

    def __init__(self):
        self.running = False
        self.last_snapshot: dict[str, Any] = {}

    def snapshot(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        self.last_snapshot = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "disk_percent": disk.percent,
            "load_average": getattr(psutil, "getloadavg", lambda: (0, 0, 0))(),
        }
        return self.last_snapshot

    def run(self, interval: int = 60) -> None:
        self.running = True
        while self.running:
            try:
                logger.info("Performance: %s", self.snapshot())
            except Exception:
                logger.exception("Performance snapshot failed")
            time.sleep(max(int(interval), 1))

    def stop(self) -> None:
        self.running = False
