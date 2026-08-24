#!/usr/bin/env python3
"""
Health Monitor — runs on VPS, reports status to GitHub.
"""
import os
import sys
import json
import time
import logging
import subprocess
import requests
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("health_monitor")

GITHUB_API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPO", "Alexkkkkk/grinch-gram-ton")
TOKEN = os.getenv("GITHUB_TOKEN", "")
HEALTH_URL = "http://localhost:3000/api/health"
CHECK_INTERVAL = 60  # seconds


def check_health() -> dict:
    """Check bot health."""
    try:
        resp = requests.get(HEALTH_URL, timeout=10)
        return {"status": "ok" if resp.status_code == 200 else "error", 
                "code": resp.status_code, "response": resp.json()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_docker() -> dict:
    """Check Docker containers."""
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            capture_output=True, text=True, cwd="/opt/bot"
        )
        return {"status": "ok", "containers": result.stdout}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_disk() -> dict:
    """Check disk usage."""
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            parts = lines[1].split()
            usage = parts[4].replace("%", "")
            return {"status": "ok" if int(usage) < 90 else "warning", 
                    "usage_percent": int(usage)}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "unknown"}


def report_to_github(status: dict):
    """Report health status to GitHub."""
    if not TOKEN:
        return
    
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # Check for existing health issue
    issues_url = f"{GITHUB_API}/repos/{REPO}/issues?state=open&labels=health-check"
    try:
        resp = requests.get(issues_url, headers=headers, timeout=30)
        issues = resp.json()
        
        body = f"""## VPS Health Report

| Check | Status | Details |
|-------|--------|---------|
| Bot API | {status['health']['status']} | {status['health']} |
| Docker | {status['docker']['status']} | OK |
| Disk | {status['disk']['status']} | {status['disk'].get('usage_percent', 'N/A')}% |

**Timestamp:** {status['timestamp']}
**Hostname:** {status['hostname']}
"""
        
        if issues:
            # Update existing
            issue_num = issues[0]["number"]
            requests.patch(
                f"{GITHUB_API}/repos/{REPO}/issues/{issue_num}",
                headers=headers,
                json={"body": body},
                timeout=30
            )
        else:
            # Create new
            requests.post(
                f"{GITHUB_API}/repos/{REPO}/issues",
                headers=headers,
                json={
                    "title": f"VPS Health: {status['health']['status'].upper()}",
                    "body": body,
                    "labels": ["health-check", "vps"],
                },
                timeout=30
            )
    except Exception as e:
        logger.error("Failed to report to GitHub: %s", e)


def main():
    while True:
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "hostname": os.uname().nodename,
            "health": check_health(),
            "docker": check_docker(),
            "disk": check_disk(),
        }
        
        logger.info("Health: %s", status['health']['status'])
        
        # Report to GitHub every 5 minutes
        if int(time.time()) % 300 < CHECK_INTERVAL:
            report_to_github(status)
        
        # Auto-restart if bot is down
        if status['health']['status'] != 'ok':
            logger.warning("Bot unhealthy, attempting restart...")
            subprocess.run(["docker-compose", "restart", "bot"], cwd="/opt/bot")
        
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
