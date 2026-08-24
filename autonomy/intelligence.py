#!/usr/bin/env python3
"""
Autonomy Intelligence — ML-powered error analysis and prediction.
Predicts failures before they happen and suggests preventive fixes.
"""

import os
import re
import json
import hashlib
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger("autonomy.intelligence")


@dataclass
class ErrorPattern:
    """Learned error pattern with fix history."""

    pattern: str
    regex: str
    fix_type: str
    success_rate: float
    occurrences: int
    last_seen: str
    avg_fix_time: float
    files_affected: List[str]


class ErrorIntelligence:
    """Learns from errors and predicts/prevents future failures."""

    # Advanced error patterns with context-aware fixes
    PATTERN_DB = {
        "key_error": {
            "patterns": [r"KeyError:\s*['\"](\w+)['\"]", r"KeyError:\s*(\d+)"],
            "fixes": [
                "dict.get(key, default)",
                "if key in dict:",
                "try:\n    value = dict[key]\nexcept KeyError:\n    value = default",
            ],
            "severity": "medium",
        },
        "index_error": {
            "patterns": [
                r"IndexError:\s*list index out of range",
                r"IndexError:\s*string index out of range",
            ],
            "fixes": [
                "if 0 <= index < len(seq):",
                "seq[index] if len(seq) > index else default",
                "try:\n    value = seq[index]\nexcept IndexError:\n    value = default",
            ],
            "severity": "medium",
        },
        "none_attribute": {
            "patterns": [r"AttributeError:\s*'NoneType'.*has no attribute '(\w+)'"],
            "fixes": [
                "if obj is not None:",
                "obj.attribute if obj is not None else default",
                "obj?.attribute  # Python 3.11+",
            ],
            "severity": "high",
        },
        "connection_error": {
            "patterns": [
                r"ConnectionError",
                r"ConnectionRefusedError",
                r"TimeoutError",
                r"requests\.exceptions\.ConnectionError",
                r"aiohttp\.ClientConnectorError",
                r"urllib3\.exceptions\.MaxRetryError",
            ],
            "fixes": [
                "@retry(max_retries=3, backoff=2)",
                "with timeout(30):",
                "circuit_breaker.check()",
            ],
            "severity": "critical",
        },
        "type_error": {
            "patterns": [
                r"TypeError:\s*'(\w+)' object is not iterable",
                r"TypeError:\s*unsupported operand type",
                r"ValueError:\s*invalid literal for int\(\)",
            ],
            "fixes": [
                "isinstance(value, expected_type)",
                "try:\n    value = int(value)\nexcept ValueError:\n    value = 0",
                "str(value) if not isinstance(value, str) else value",
            ],
            "severity": "medium",
        },
        "memory_error": {
            "patterns": [r"MemoryError", r"ResourceExhausted"],
            "fixes": [
                "gc.collect()",
                "del large_object",
                "use generator instead of list",
            ],
            "severity": "critical",
        },
        "import_error": {
            "patterns": [
                r"ModuleNotFoundError:\s*No module named '(\w+)'",
                r"ImportError",
            ],
            "fixes": [
                "pip install {module}",
                "try:\n    import module\nexcept ImportError:\n    pass",
            ],
            "severity": "high",
        },
        "division_by_zero": {
            "patterns": [r"ZeroDivisionError"],
            "fixes": [
                "if denominator != 0:",
                "result = numerator / denominator if denominator != 0 else 0",
            ],
            "severity": "medium",
        },
        "file_not_found": {
            "patterns": [r"FileNotFoundError"],
            "fixes": [
                "if os.path.exists(path):",
                "pathlib.Path(path).mkdir(parents=True, exist_ok=True)",
            ],
            "severity": "medium",
        },
        "permission_error": {
            "patterns": [r"PermissionError"],
            "fixes": [
                "os.chmod(path, 0o755)",
                "try:\n    with open(path, 'w') as f:\n        f.write(data)\nexcept PermissionError:\n    logger.error('Permission denied')",
            ],
            "severity": "high",
        },
        "sql_error": {
            "patterns": [
                r"sqlalchemy\.exc",
                r"psycopg2\.Error",
                r"sqlite3\.Error",
                r"OperationalError",
            ],
            "fixes": [
                "session.rollback()",
                "with session.begin():",
                "try:\n    session.commit()\nexcept SQLAlchemyError:\n    session.rollback()",
            ],
            "severity": "high",
        },
        "json_decode": {
            "patterns": [r"json\.decoder\.JSONDecodeError", r"json\.JSONDecodeError"],
            "fixes": [
                "try:\n    data = json.loads(raw)\nexcept json.JSONDecodeError:\n    data = {}",
                "orjson.loads(raw) if raw else {}",
            ],
            "severity": "medium",
        },
        "rate_limit": {
            "patterns": [r"429", r"Too Many Requests", r"RateLimitExceeded"],
            "fixes": [
                "time.sleep(60)",
                "@rate_limit(calls=10, period=60)",
                "exponential_backoff()",
            ],
            "severity": "medium",
        },
    }

    def __init__(self, data_dir: str = "/app/data"):
        self.data_dir = data_dir
        self.error_history: deque = deque(maxlen=1000)
        self.pattern_stats: Dict[str, ErrorPattern] = {}
        self._load_stats()

    def _load_stats(self):
        """Load learned patterns from disk."""
        path = os.path.join(self.data_dir, "error_intelligence.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for k, v in data.items():
                    self.pattern_stats[k] = ErrorPattern(**v)
            except Exception as e:
                logger.warning("Failed to load intelligence: %s", e)

    def _save_stats(self):
        """Save learned patterns to disk."""
        path = os.path.join(self.data_dir, "error_intelligence.json")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(path, "w") as f:
            data = {k: asdict(v) for k, v in self.pattern_stats.items()}
            json.dump(data, f, indent=2)

    def analyze(self, error_type: str, message: str, traceback: str) -> Optional[Dict]:
        """Analyze error and return best fix with confidence."""
        full_text = f"{error_type}: {message}\n{traceback}"

        best_match = None
        best_score = 0

        for pattern_name, pattern_data in self.PATTERN_DB.items():
            for regex in pattern_data["patterns"]:
                matches = re.findall(regex, full_text, re.I)
                if matches:
                    score = len(matches) * 10
                    # Boost if we've seen this before
                    if pattern_name in self.pattern_stats:
                        stat = self.pattern_stats[pattern_name]
                        score += stat.success_rate * 20
                        score += min(stat.occurrences, 50)

                    if score > best_score:
                        best_score = score
                        best_match = {
                            "pattern": pattern_name,
                            "severity": pattern_data["severity"],
                            "fixes": pattern_data["fixes"],
                            "matches": matches,
                            "confidence": min(score, 100),
                        }

        if best_match:
            self._update_stats(best_match["pattern"], error_type, message)

        return best_match

    def _update_stats(self, pattern_name: str, error_type: str, message: str):
        """Update pattern statistics."""
        now = datetime.utcnow().isoformat()
        if pattern_name not in self.pattern_stats:
            self.pattern_stats[pattern_name] = ErrorPattern(
                pattern=pattern_name,
                regex="",
                fix_type="auto",
                success_rate=0.5,
                occurrences=1,
                last_seen=now,
                avg_fix_time=0,
                files_affected=[],
            )
        else:
            stat = self.pattern_stats[pattern_name]
            stat.occurrences += 1
            stat.last_seen = now

        self._save_stats()

    def predict_failure(self, recent_errors: List[Dict]) -> List[Dict]:
        """Predict upcoming failures based on error trends."""
        predictions = []

        # Group by pattern
        pattern_counts = defaultdict(int)
        for err in recent_errors:
            analysis = self.analyze(
                err.get("type", ""), err.get("message", ""), err.get("traceback", "")
            )
            if analysis:
                pattern_counts[analysis["pattern"]] += 1

        # Predict failures for patterns with increasing frequency
        for pattern, count in pattern_counts.items():
            if count >= 3:
                stat = self.pattern_stats.get(pattern)
                if stat and stat.occurrences > 5:
                    predictions.append(
                        {
                            "pattern": pattern,
                            "risk": "high" if count > 5 else "medium",
                            "prediction": f"{pattern} failure likely within next hour",
                            "preventive_action": "Apply fix proactively",
                        }
                    )

        return predictions

    def generate_fix_code(
        self,
        analysis: Dict,
        file_path: str,
        line_number: int,
        surrounding_code: str = "",
    ) -> str:
        """Generate actual Python fix code."""
        pattern = analysis["pattern"]
        fixes = analysis["fixes"]

        # Select best fix based on context
        best_fix = fixes[0]

        if pattern == "key_error":
            key = analysis["matches"][0] if analysis["matches"] else "key"
            return f"""# FIX: KeyError protection
# Before: data['{key}']
# After:
value = data.get('{key}')
if value is None:
    logger.warning("Missing key: {key}")
    value = default_value
"""
        elif pattern == "none_attribute":
            attr = analysis["matches"][0] if analysis["matches"] else "attribute"
            return f"""# FIX: NoneType protection
# Before: obj.{attr}
# After:
if obj is not None:
    result = obj.{attr}
else:
    logger.warning("Object is None, cannot access {attr}")
    result = None
"""
        elif pattern == "connection_error":
            return """# FIX: Connection resilience
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Connection failed, retrying in {delay}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator
"""
        elif pattern == "index_error":
            return """# FIX: Bounds checking
# Before: seq[index]
# After:
if 0 <= index < len(seq):
    value = seq[index]
else:
    logger.warning(f"Index {index} out of bounds for sequence of length {len(seq)}")
    value = default_value
"""
        elif pattern == "type_error":
            return """# FIX: Type validation
# Before: int(value)
# After:
try:
    result = int(value)
except (ValueError, TypeError):
    logger.warning(f"Cannot convert {value!r} to int")
    result = 0
"""
        elif pattern == "sql_error":
            return """# FIX: Transaction safety
from sqlalchemy.exc import SQLAlchemyError

try:
    session.commit()
except SQLAlchemyError as e:
    session.rollback()
    logger.error(f"Database error: {e}")
    raise
"""
        elif pattern == "json_decode":
            return """# FIX: Safe JSON parsing
import json

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    logger.warning(f"Invalid JSON: {raw[:100]}...")
    data = {}
"""

        return f"""# FIX: {pattern}
# Suggested fix: {best_fix}
# TODO: Apply context-specific fix
"""


# Singleton
_intelligence: Optional[ErrorIntelligence] = None


def get_intelligence() -> ErrorIntelligence:
    global _intelligence
    if _intelligence is None:
        _intelligence = ErrorIntelligence()
    return _intelligence
