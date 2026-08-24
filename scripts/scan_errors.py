#!/usr/bin/env python3
"""
Scan logs for errors and report to GitHub.
"""
import os
import re
import sys
import glob
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/bot")
from error_reporter_v2 import report_error

LOG_PATTERNS = [
    "/var/log/grinch/*.log",
    "/opt/bot/logs/*.log",
]

ERROR_PATTERNS = [
    re.compile(r'(ERROR|CRITICAL|Exception|Traceback)', re.I),
]


def scan_logs():
    """Scan log files for new errors."""
    for pattern in LOG_PATTERNS:
        for log_file in glob.glob(pattern):
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            # Check last 100 lines
            for line in lines[-100:]:
                for pattern in ERROR_PATTERNS:
                    if pattern.search(line):
                        # Create synthetic exception
                        class LogError(Exception):
                            pass
                        try:
                            raise LogError(line.strip())
                        except Exception as e:
                            report_error(e, "error")
                        break


if __name__ == "__main__":
    scan_logs()
