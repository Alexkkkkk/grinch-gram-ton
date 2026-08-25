#!/usr/bin/env python3
"""
Error Reporter v3 — VPS → GitHub Issues + Auto-Fix with Intelligence Engine

Отправляет ошибки с VPS в GitHub Issues.
При повторяющихся ошибках — создаёт PR с автоматическим исправлением.
Uses autonomy.intelligence for ML-powered error analysis.
"""

import hashlib
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests

# Add project root for autonomy imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from autonomy.intelligence import get_intelligence
except ImportError:
    get_intelligence = None

logger = logging.getLogger("error_reporter_v3")

GITHUB_API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPO", "Alexkkkkk/grinch-gram-ton")
TOKEN = os.getenv("GITHUB_TOKEN", "")


@dataclass
class ErrorReport:
    """Structured error report."""

    timestamp: str
    hostname: str
    error_type: str
    message: str
    traceback: str
    file_path: str
    line_number: int
    function: str
    severity: str
    count: int = 1
    hash_id: str = ""
    intelligence_analysis: Optional[Dict] = None

    def __post_init__(self):
        if not self.hash_id:
            content = (
                f"{self.error_type}:{self.message}:{self.file_path}:{self.line_number}"
            )
            self.hash_id = hashlib.sha256(content.encode()).hexdigest()[:16]


class GitHubIssueManager:
    """Manage GitHub Issues for error tracking."""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._issue_cache: Dict[str, dict] = {}

    def _api(self, endpoint: str, method="GET", data=None) -> dict:
        url = f"{GITHUB_API}/repos/{self.repo}/{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, timeout=30)
            elif method == "POST":
                resp = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method == "PATCH":
                resp = requests.patch(url, headers=self.headers, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("GitHub API error: %s", e)
            return {}

    def find_issue_by_hash(self, hash_id: str) -> Optional[dict]:
        if hash_id in self._issue_cache:
            return self._issue_cache[hash_id]

        issues = self._api("issues?state=open&labels=auto-error,needs-fix&per_page=100")
        for issue in issues:
            if hash_id in issue.get("body", ""):
                self._issue_cache[hash_id] = issue
                return issue
        return None

    def create_issue(self, report: ErrorReport) -> Optional[dict]:
        title = (
            f"[{report.severity.upper()}] {report.error_type}: {report.message[:80]}"
        )

        # Add intelligence analysis if available
        intel_section = ""
        if report.intelligence_analysis:
            intel = report.intelligence_analysis
            intel_section = f"""
### Intelligence Analysis
| Field | Value |
|-------|-------|
| **Pattern** | `{intel.get('pattern', 'unknown')}` |
| **Confidence** | {intel.get('confidence', 0)}% |
| **Severity** | {intel.get('severity', 'unknown')} |
| **Suggested Fixes** | {', '.join(intel.get('fixes', [])[:3])} |
"""

        body = f"""## Error Report

| Field | Value |
|-------|-------|
| **Hash** | `{report.hash_id}` |
| **Severity** | {report.severity} |
| **Timestamp** | {report.timestamp} |
| **Hostname** | {report.hostname} |
| **File** | `{report.file_path}` |
| **Line** | {report.line_number} |
| **Function** | `{report.function}` |
| **Count** | {report.count} |
{intel_section}

### Traceback
```python
{report.traceback}
```

---
*This issue was created automatically by error_reporter_v3 with Intelligence Engine*
"""
        data = {
            "title": title,
            "body": body,
            "labels": ["auto-error", "needs-fix", report.severity],
        }
        result = self._api("issues", "POST", data)
        if result:
            self._issue_cache[report.hash_id] = result
            logger.info(
                "Created GitHub Issue #%s for error %s",
                result.get("number"),
                report.hash_id,
            )
        return result

    def update_issue(self, issue_number: int, report: ErrorReport) -> Optional[dict]:
        body_addition = (
            f"\n\n### New occurrence at {report.timestamp}\nCount: {report.count}"
        )
        issue = self._api(f"issues/{issue_number}")
        new_body = issue.get("body", "") + body_addition
        data = {"body": new_body}
        return self._api(f"issues/{issue_number}", "PATCH", data)

    def create_fix_branch(
        self, error_hash: str, file_path: str, fix_description: str
    ) -> str:
        branch_name = (
            f"auto-fix/{error_hash[:8]}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        main_ref = self._api("git/refs/heads/main")
        sha = main_ref.get("object", {}).get("sha", "")
        self._api(
            "git/refs",
            "POST",
            {
                "ref": f"refs/heads/{branch_name}",
                "sha": sha,
            },
        )
        logger.info("Created fix branch: %s", branch_name)
        return branch_name

    def create_pull_request(self, branch: str, title: str, body: str) -> Optional[dict]:
        data = {
            "title": f"[AUTO-FIX] {title}",
            "body": body,
            "head": branch,
            "base": "main",
            "labels": ["auto-fix", "bot"],
        }
        result = self._api("pulls", "POST", data)
        if result:
            logger.info("Created PR #%s: %s", result.get("number"), title)
        return result


class AutoFixEngine:
    """Automatically generate fixes for common errors using Intelligence Engine."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.intelligence = get_intelligence() if get_intelligence else None

    def analyze(self, report: ErrorReport) -> Optional[Dict]:
        """Analyze error using Intelligence Engine."""
        if self.intelligence:
            return self.intelligence.analyze(
                report.error_type, report.message, report.traceback
            )
        return None

    def generate_fix(self, analysis: Dict, report: ErrorReport) -> Optional[str]:
        """Generate code fix."""
        if self.intelligence:
            return self.intelligence.generate_fix_code(
                analysis, report.file_path, report.line_number
            )
        return None


class ErrorReporterV3:
    """Main error reporter — VPS ↔ GitHub sync with Intelligence."""

    def __init__(self):
        self.github = GitHubIssueManager(TOKEN, REPO)
        self.fix_engine = AutoFixEngine()
        self.error_counts: Dict[str, int] = {}
        self._hostname = os.uname().nodename
        self.intelligence = get_intelligence() if get_intelligence else None

    def report(
        self, exception: Exception, severity: str = "error", context: dict = None
    ):
        """Report an exception to GitHub."""
        tb = traceback.format_exc()
        tb_lines = tb.strip().split("\n")

        file_path = "unknown"
        line_number = 0
        function = "unknown"

        for line in reversed(tb_lines):
            match = re.search(r'File "([^"]+)", line (\d+), in (\w+)', line)
            if match:
                file_path = match.group(1)
                line_number = int(match.group(2))
                function = match.group(3)
                break

        report = ErrorReport(
            timestamp=datetime.utcnow().isoformat(),
            hostname=self._hostname,
            error_type=type(exception).__name__,
            message=str(exception),
            traceback=tb,
            file_path=file_path,
            line_number=line_number,
            function=function,
            severity=severity,
        )

        # Intelligence analysis
        if self.intelligence:
            report.intelligence_analysis = self.intelligence.analyze(
                report.error_type, report.message, report.traceback
            )

        # Count occurrences
        self.error_counts[report.hash_id] = self.error_counts.get(report.hash_id, 0) + 1
        report.count = self.error_counts[report.hash_id]

        # Check for existing issue
        existing = self.github.find_issue_by_hash(report.hash_id)

        if existing:
            self.github.update_issue(existing["number"], report)
            logger.info(
                "Updated issue #%s for error %s (count=%d)",
                existing["number"],
                report.hash_id,
                report.count,
            )

            if report.count >= 3 and severity in ("critical", "error"):
                self._trigger_auto_fix(report)
        else:
            self.github.create_issue(report)

    def _trigger_auto_fix(self, report: ErrorReport):
        """Trigger automatic fix for repeating errors."""
        logger.info("Triggering auto-fix for error %s", report.hash_id)

        analysis = self.fix_engine.analyze(report)
        if not analysis:
            logger.warning("No auto-fix available for error %s", report.hash_id)
            return

        fix_code = self.fix_engine.generate_fix(analysis, report)
        if not fix_code:
            return

        branch = self.github.create_fix_branch(
            report.hash_id, report.file_path, analysis.get("description", "auto-fix")
        )

        pr_body = f"""## Auto-Fix for Error `{report.hash_id}`

**Error:** {report.error_type}: {report.message}
**File:** `{report.file_path}:{report.line_number}`
**Occurrences:** {report.count}
**Pattern:** `{analysis.get('pattern', 'unknown')}`
**Confidence:** {analysis.get('confidence', 0)}%

### Suggested Fix
```python
{fix_code}
```

---
*This PR was created automatically by error_reporter_v3 with Intelligence Engine*
"""

        self.github.create_pull_request(
            branch, f"{report.error_type} in {report.file_path}", pr_body
        )


# Global instance
_reporter: Optional[ErrorReporterV3] = None


def get_reporter() -> ErrorReporterV3:
    global _reporter
    if _reporter is None:
        _reporter = ErrorReporterV3()
    return _reporter


def report_error(exception: Exception, severity: str = "error", context: dict = None):
    """Convenience function to report an error."""
    try:
        get_reporter().report(exception, severity, context)
    except Exception as e:
        logger.error("Failed to report error: %s", e)


def auto_report(severity: str = "error"):
    """Decorator for automatic error reporting."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                report_error(
                    e,
                    severity,
                    {"func": func.__name__, "args": str(args), "kwargs": str(kwargs)},
                )
                raise

        return wrapper

    return decorator


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        raise ValueError("Test error from VPS with Intelligence Engine")
    except Exception as e:
        report_error(e, "critical")
