#!/usr/bin/env python3
"""
Grok autonomous repository agent (stdlib only).

Modes
-----
audit : inspect repo -> find bugs / TODOs / failing CI / open issues
        -> ask Grok for fixes -> run the test gate -> apply (or revert).
fix   : same, but scoped to one GitHub issue (GROK_ISSUE_NUMBER).

The workflow then turns the working-tree changes into a Pull Request.

Env:
  XAI_API_KEY        required  (xAI / Grok API key)
  GITHUB_TOKEN       provided by Actions
  GITHUB_REPOSITORY  owner/repo
  GROK_MODEL         default grok-4.6
  GROK_MODE          audit | fix
  GROK_ISSUE_NUMBER  issue number for fix mode
  XAI_BASE_URL       default https://api.x.ai/v1
  GROK_TEST_CMD      explicit test command (else auto-detected)
  GROK_TEST_GATE     1 = revert all edits if tests fail (default 1)
  GROK_TEST_TIMEOUT  seconds, default 1800
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _resolve_provider():
    """Pick the first configured LLM provider, so the agent runs with whatever
    key the repository already has: xAI Grok -> Groq -> OpenAI."""
    if os.environ.get("XAI_API_KEY", "").strip():
        return (
            "xai",
            os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
            os.environ["XAI_API_KEY"].strip(),
            os.environ.get("GROK_MODEL", "grok-4.6").strip(),
        )
    if os.environ.get("GROQ_API_KEY", "").strip():
        return (
            "groq",
            "https://api.groq.com/openai/v1",
            os.environ["GROQ_API_KEY"].strip(),
            os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        )
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return (
            "openai",
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            os.environ["OPENAI_API_KEY"].strip(),
            os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip(),
        )
    return (None, "", "", "")


PROVIDER, XAI_BASE, XAI_KEY, MODEL = _resolve_provider()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
MODE = os.environ.get("GROK_MODE", "audit").strip().lower()
ISSUE = os.environ.get("GROK_ISSUE_NUMBER", "").strip()

MAX_FILES = int(os.environ.get("GROK_MAX_FILES", "60"))
MAX_TOTAL_BYTES = int(os.environ.get("GROK_MAX_BYTES", "150000"))
MAX_FILE_BYTES = int(os.environ.get("GROK_MAX_FILE_BYTES", "20000"))
MAX_EDITS = int(os.environ.get("GROK_MAX_EDITS", "25"))
TEST_CMD = os.environ.get("GROK_TEST_CMD", "").strip()
TEST_GATE = os.environ.get("GROK_TEST_GATE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
TEST_TIMEOUT = int(os.environ.get("GROK_TEST_TIMEOUT", "1800"))
REPORT = Path("GROK_REPORT.md")

CODE_EXT = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".sol",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".sh",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".sql",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".env.example",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    ".idea",
    ".vscode",
    "site-packages",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
}


def log(msg: str) -> None:
    print(f"[grok-agent] {msg}", flush=True)


def http_json(url: str, payload=None, headers=None, retries: int = 4):
    """Tiny HTTP client with exponential backoff for 429 / 5xx / network errors."""
    data = json.dumps(payload).encode() if payload is not None else None
    hdr = {"User-Agent": "grok-agent", "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    if data:
        hdr["Content-Type"] = "application/json"
    delay, last = 2.0, None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers=hdr, method="POST" if data else "GET"
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read().decode("utf-8", "replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            last = e
            body = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                log(f"HTTP {e.code}, backoff {delay:.0f}s ({attempt + 1}/{retries})")
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {e.code}: {body[:400]}") from e
        except urllib.error.URLError as e:
            last = e
            if attempt < retries - 1:
                log(f"network error ({attempt + 1}/{retries}), backoff {delay:.0f}s")
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"network failure: {e}") from e
    raise RuntimeError(f"request failed: {last}")


def gh(path: str):
    if not (GH_TOKEN and REPO):
        return None
    try:
        return http_json(
            f"https://api.github.com/repos/{REPO}{path}",
            headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except Exception as exc:  # noqa: BLE001
        log(f"GitHub API warning on {path}: {exc}")
        return None


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout
        files = [Path(p) for p in out.splitlines() if p.strip()]
    except Exception:  # noqa: BLE001
        files = [p for p in Path(".").rglob("*") if p.is_file()]
    result = []
    for p in files:
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in CODE_EXT and p.stat().st_size <= MAX_FILE_BYTES:
            result.append(p)
        if len(result) >= MAX_FILES:
            break
    return result


def repomap(files: list[Path]) -> str:
    blocks, total = [], 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if total + len(text) > MAX_TOTAL_BYTES:
            break
        total += len(text)
        blocks.append(f"### FILE: {p}\n```\n{text}\n```")
    return "\n\n".join(blocks)


def failing_ci() -> str:
    runs = gh("/actions/runs?status=failure&per_page=5")
    if not runs or not runs.get("workflow_runs"):
        return "No failing workflow runs."
    lines = []
    for r in runs["workflow_runs"]:
        lines.append(
            f"- {r.get('name')} #{r.get('run_number')} "
            f"branch={r.get('head_branch')} "
            f"conclusion={r.get('conclusion')} url={r.get('html_url')}"
        )
    return "\n".join(lines)


def open_issues() -> str:
    data = gh("/issues?state=open&per_page=15")
    if not data:
        return "No open issues."
    lines = []
    for i in data:
        if "pull_request" in i:
            continue
        lines.append(
            f"- #{i.get('number')} {i.get('title')} "
            f"[{', '.join(l['name'] for l in i.get('labels', []))}]"
        )
    return "\n".join(lines) or "No open issues."


def open_branches() -> str:
    data = gh("/branches?per_page=50")
    if not data:
        return "unknown"
    return ", ".join(b["name"] for b in data)


def issue_body(number: str) -> str:
    data = gh(f"/issues/{number}")
    if not data:
        return ""
    return f"#{data.get('number')} {data.get('title')}\n\n{data.get('body') or ''}"


def call_grok(system: str, user: str) -> str:
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = http_json(
        f"{XAI_BASE}/chat/completions",
        payload,
        headers={"Authorization": f"Bearer {XAI_KEY}"},
    )
    return resp["choices"][0]["message"]["content"]


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def safe_apply(edits: list[dict]) -> list[str]:
    applied = []
    for e in edits[:MAX_EDITS]:
        rel = str(e.get("path", "")).strip().lstrip("/")
        content = e.get("content")
        if not rel or content is None or ".." in Path(rel).parts:
            log(f"skip unsafe/invalid edit: {rel!r}")
            continue
        target = Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        old = (
            target.read_text(encoding="utf-8", errors="replace")
            if target.exists()
            else ""
        )
        if old == content:
            log(f"no change: {rel}")
            continue
        target.write_text(content, encoding="utf-8")
        applied.append(rel)
        log(f"patched: {rel} ({len(old)} -> {len(content)} bytes)")
    return applied


# --------------------------------------------------------------------------
# Test gate: prove the edits do not break the repository before opening a PR.
# --------------------------------------------------------------------------
def detect_test_cmd() -> str | None:
    if TEST_CMD:
        return TEST_CMD
    if Path("package.json").exists():
        return "npm ci --no-audit --no-fund && npm test --if-present"
    py_project = any(
        Path(p).exists()
        for p in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "tests")
    )
    if py_project:
        return (
            "python -m pip install -q -r requirements.txt 2>/dev/null; "
            "python -m pytest -q"
        )
    if Path("Dockerfile").exists():
        return "docker build -t grok-ci-check ."
    return None


def run_test_gate() -> tuple[bool, str, str]:
    """Returns (ok, command, tail_of_output). ok=True also when no command found."""
    cmd = detect_test_cmd()
    if not cmd:
        log("test gate: no test command detected, skipping")
        return True, "(none detected)", "No tests found - gate skipped."
    log(f"test gate: running `{cmd}`")
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=TEST_TIMEOUT
        )
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0
        log(f"test gate: exit={p.returncode} -> {'PASS' if ok else 'FAIL'}")
        return ok, cmd, out[-4000:]
    except subprocess.TimeoutExpired:
        return False, cmd, f"TIMEOUT after {TEST_TIMEOUT}s"
    except Exception as exc:  # noqa: BLE001
        return False, cmd, f"runner error: {exc}"


def revert_worktree() -> None:
    """Drop every agent edit so a failing gate cannot reach a Pull Request."""
    subprocess.run(["git", "checkout", "--", "."], capture_output=True, text=True)
    subprocess.run(
        ["git", "clean", "-fd", "-e", REPORT.name], capture_output=True, text=True
    )
    log("worktree reverted to HEAD")


SYSTEM = (
    "You are Grok, an autonomous senior software engineer maintaining a GitHub "
    "repository while the team is idle. Fix real bugs, remove dead code, tighten "
    "error handling, repair broken tests and CI configuration. Never invent new "
    "features or secrets. Preserve the public API and file layout unless a change "
    "is required for correctness. Every change MUST keep the existing test suite "
    "green. Respond with STRICT JSON only, no prose:\n"
    '{"summary": "<short markdown summary>", "edits": [{"path": "<repo-relative path>",'
    ' "content": "<FULL new file content>"}], "recommendation": "<what a human '
    'should check>"}'
)


def build_user_prompt() -> str:
    files = tracked_files()
    parts = [
        f"Repository: {REPO or 'local'}",
        f"Branch list: {open_branches()}",
        "## Failing CI runs\n" + failing_ci(),
        "## Open issues\n" + open_issues(),
    ]
    if MODE == "fix" and ISSUE:
        parts.append(f"## Target issue\n{issue_body(ISSUE)}")
        parts.append("Task: implement the minimal fix for the target issue.")
    else:
        parts.append("Task: audit the codebase and apply safe correctness fixes.")
    parts.append("## Repository content\n" + repomap(files))
    return "\n\n".join(parts)


def main() -> int:
    if not XAI_KEY:
        log(
            "ERROR: no API key - set XAI_API_KEY (Grok), GROQ_API_KEY (Groq) "
            "or OPENAI_API_KEY as a repository secret."
        )
        return 2
    log(f"provider={PROVIDER} model={MODEL} repo={REPO or 'local'} gate={TEST_GATE}")
    user = build_user_prompt()
    log(f"prompt bytes={len(user)}")
    raw = call_grok(SYSTEM, user)
    data = parse_json(raw)
    edits = data.get("edits") or []
    applied = safe_apply(edits)

    gate_ok, gate_cmd, gate_out = True, "(not run)", "No edits applied."
    if applied and TEST_GATE:
        gate_ok, gate_cmd, gate_out = run_test_gate()
        if not gate_ok:
            revert_worktree()
            applied = []

    lines = [
        f"# Grok autonomous run ({MODE})",
        "",
        f"- Model: `{MODEL}`",
        f"- Files scanned: {len(tracked_files())}",
        f"- Proposed edits: {len(edits)}",
        f"- Applied edits: {len(applied)}",
        f"- Test gate: {'PASSED' if gate_ok else 'FAILED (edits reverted)'}",
        f"- Test command: `{gate_cmd}`",
        "",
        "## Summary",
        "",
        data.get("summary", "(none)"),
        "",
        "## Files changed",
        "",
        *([f"- `{p}`" for p in applied] or ["_none_ - repository already clean_"]),
        "",
    ]
    if not gate_ok:
        lines += ["## Test output (failure)", "", "```", gate_out, "```", ""]
    lines += [
        "## Recommendation for a human reviewer",
        "",
        data.get("recommendation", "(none)"),
        "",
        "> Автономный агент. Проверьте diff перед мержем.",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log(f"report written, {len(applied)} file(s) changed, gate_ok={gate_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
