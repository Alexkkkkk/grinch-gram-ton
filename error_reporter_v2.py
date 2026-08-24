#!/usr/bin/env python3
"""
Error Reporter v2 — VPS → GitHub Issues + Auto-Fix

Отправляет ошибки с VPS в GitHub Issues.
При повторяющихся ошибках — создаёт PR с автоматическим исправлением.
"""
import os
import re
import sys
import json
import hashlib
import logging
import traceback
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

logger = logging.getLogger("error_reporter_v2")

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
    severity: str  # critical, error, warning
    count: int = 1
    hash_id: str = ""
    
    def __post_init__(self):
        if not self.hash_id:
            content = f"{self.error_type}:{self.message}:{self.file_path}:{self.line_number}"
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
        """Find existing issue by error hash."""
        if hash_id in self._issue_cache:
            return self._issue_cache[hash_id]
        
        # Search open issues with the hash
        issues = self._api(f"issues?state=open&labels=auto-error,needs-fix&per_page=100")
        for issue in issues:
            if hash_id in issue.get("body", ""):
                self._issue_cache[hash_id] = issue
                return issue
        return None
    
    def create_issue(self, report: ErrorReport) -> Optional[dict]:
        """Create new GitHub Issue for error."""
        title = f"[{report.severity.upper()}] {report.error_type}: {report.message[:80]}"
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

### Traceback
```python
{report.traceback}
```

---
*This issue was created automatically by error_reporter_v2*
"""
        data = {
            "title": title,
            "body": body,
            "labels": ["auto-error", "needs-fix", report.severity],
        }
        result = self._api("issues", "POST", data)
        if result:
            self._issue_cache[report.hash_id] = result
            logger.info("Created GitHub Issue #%s for error %s", result.get("number"), report.hash_id)
        return result
    
    def update_issue(self, issue_number: int, report: ErrorReport) -> Optional[dict]:
        """Update existing issue with new occurrence."""
        body_addition = f"\n\n### New occurrence at {report.timestamp}\nCount: {report.count}"
        issue = self._api(f"issues/{issue_number}")
        new_body = issue.get("body", "") + body_addition
        data = {"body": new_body}
        return self._api(f"issues/{issue_number}", "PATCH", data)
    
    def create_fix_branch(self, error_hash: str, file_path: str, fix_description: str) -> str:
        """Create a new branch for auto-fix."""
        branch_name = f"auto-fix/{error_hash[:8]}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Get main SHA
        main_ref = self._api("git/refs/heads/main")
        sha = main_ref.get("object", {}).get("sha", "")
        
        # Create branch
        self._api("git/refs", "POST", {
            "ref": f"refs/heads/{branch_name}",
            "sha": sha,
        })
        
        logger.info("Created fix branch: %s", branch_name)
        return branch_name
    
    def create_pull_request(self, branch: str, title: str, body: str) -> Optional[dict]:
        """Create PR with auto-fix."""
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
    """Automatically generate fixes for common errors."""
    
    COMMON_FIXES = {
        r"KeyError:\s*'(\w+)'": {
            "type": "add_key_check",
            "description": "Add .get() or key check",
        },
        r"IndexError:\s*list index out of range": {
            "type": "add_bounds_check",
            "description": "Add bounds checking",
        },
        r"AttributeError:\s*'NoneType'.*has no attribute '(\w+)'": {
            "type": "add_none_check",
            "description": "Add None check before attribute access",
        },
        r"ConnectionError|TimeoutError|requests\.exceptions\.ConnectionError": {
            "type": "add_retry",
            "description": "Add retry logic with backoff",
        },
        r"ValueError:\s*invalid literal for int\(\) with base 10:\s*'(\w+)'": {
            "type": "add_type_check",
            "description": "Add type validation before conversion",
        },
        r"ModuleNotFoundError|ImportError": {
            "type": "fix_import",
            "description": "Fix or add missing import",
        },
    }
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
    
    def analyze(self, report: ErrorReport) -> Optional[Dict]:
        """Analyze error and suggest fix."""
        for pattern, fix_info in self.COMMON_FIXES.items():
            if re.search(pattern, report.message + report.traceback):
                return {
                    "error_pattern": pattern,
                    "fix_type": fix_info["type"],
                    "description": fix_info["description"],
                    "file_path": report.file_path,
                    "line_number": report.line_number,
                }
        return None
    
    def generate_fix(self, analysis: Dict, report: ErrorReport) -> Optional[str]:
        """Generate code fix as string."""
        fix_type = analysis["fix_type"]
        file_path = analysis["file_path"]
        
        if fix_type == "add_retry":
            return self._generate_retry_fix(file_path, analysis["line_number"])
        elif fix_type == "add_none_check":
            return self._generate_none_check_fix(file_path, analysis["line_number"])
        elif fix_type == "add_bounds_check":
            return self._generate_bounds_check_fix(file_path, analysis["line_number"])
        elif fix_type == "add_key_check":
            return self._generate_key_check_fix(file_path, analysis["line_number"])
        return None
    
    def _generate_retry_fix(self, file_path: str, line: int) -> str:
        return f"""# Auto-fix: Add retry logic
import time
from functools import wraps

def retry_on_error(max_retries=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as e:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(delay * (2 ** attempt))
            return None
        return wrapper
    return decorator
"""
    
    def _generate_none_check_fix(self, file_path: str, line: int) -> str:
        return "# Auto-fix: Add None check before attribute access\n# Before: obj.attribute\n# After: obj.attribute if obj is not None else default"
    
    def _generate_bounds_check_fix(self, file_path: str, line: int) -> str:
        return "# Auto-fix: Add bounds checking\n# Before: list[index]\n# After: list[index] if 0 <= index < len(list) else default"
    
    def _generate_key_check_fix(self, file_path: str, line: int) -> str:
        return "# Auto-fix: Use .get() instead of direct key access\n# Before: dict[key]\n# After: dict.get(key, default)"


class ErrorReporterV2:
    """Main error reporter — VPS ↔ GitHub sync."""
    
    def __init__(self):
        self.github = GitHubIssueManager(TOKEN, REPO)
        self.fix_engine = AutoFixEngine()
        self.error_counts: Dict[str, int] = {}
        self._hostname = os.uname().nodename
    
    def report(self, exception: Exception, severity: str = "error", context: dict = None):
        """Report an exception to GitHub."""
        tb = traceback.format_exc()
        tb_lines = tb.strip().split("\n")
        
        # Extract file and line from traceback
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
        
        # Count occurrences
        self.error_counts[report.hash_id] = self.error_counts.get(report.hash_id, 0) + 1
        report.count = self.error_counts[report.hash_id]
        
        # Check for existing issue
        existing = self.github.find_issue_by_hash(report.hash_id)
        
        if existing:
            # Update existing issue
            self.github.update_issue(existing["number"], report)
            logger.info("Updated issue #%s for error %s (count=%d)", 
                       existing["number"], report.hash_id, report.count)
            
            # If error repeats > 3 times, trigger auto-fix
            if report.count >= 3 and severity in ("critical", "error"):
                self._trigger_auto_fix(report)
        else:
            # Create new issue
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
        
        # Create fix branch and PR
        branch = self.github.create_fix_branch(
            report.hash_id, 
            report.file_path,
            analysis["description"]
        )
        
        pr_body = f"""## Auto-Fix for Error `{report.hash_id}`

**Error:** {report.error_type}: {report.message}
**File:** `{report.file_path}:{report.line_number}`
**Occurrences:** {report.count}

### Suggested Fix
{analysis["description"]}

```python
{fix_code}
```

---
*This PR was created automatically by error_reporter_v2*
"""
        
        self.github.create_pull_request(
            branch,
            f"{report.error_type} in {report.file_path}",
            pr_body
        )


# Global instance
_reporter: Optional[ErrorReporterV2] = None

def get_reporter() -> ErrorReporterV2:
    global _reporter
    if _reporter is None:
        _reporter = ErrorReporterV2()
    return _reporter

def report_error(exception: Exception, severity: str = "error", context: dict = None):
    """Convenience function to report an error."""
    try:
        get_reporter().report(exception, severity, context)
    except Exception as e:
        logger.error("Failed to report error: %s", e)

# Decorator for automatic error reporting
def auto_report(severity: str = "error"):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                report_error(e, severity, {"func": func.__name__, "args": str(args), "kwargs": str(kwargs)})
                raise
        return wrapper
    return decorator


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    try:
        raise ValueError("Test error from VPS")
    except Exception as e:
        report_error(e, "critical")
