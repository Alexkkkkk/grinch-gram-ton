#!/usr/bin/env python3
"""Generate automatic fix for GitHub issue using Intelligence Engine or OpenAI."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from autonomy.intelligence import get_intelligence
except ImportError:
    get_intelligence = None


def main():
    issue_body = os.environ.get("ISSUE_BODY", "")
    if not issue_body:
        print("No issue body")
        return 0

    # Extract error info
    error_type_match = re.search(r"\*\*Error Type\*\*\s*\|\s*`([^`]+)`", issue_body)
    message_match = re.search(r"\*\*Message\*\*\s*\|\s*`([^`]+)`", issue_body)
    traceback_match = re.search(
        r"### Traceback\n```python\n(.*?)\n```", issue_body, re.DOTALL
    )
    file_match = re.search(r"\*\*File\*\*\s*\|\s*`([^`]+)`", issue_body)
    line_match = re.search(r"\*\*Line\*\*\s*\|\s*(\d+)", issue_body)

    error_type = error_type_match.group(1) if error_type_match else "Unknown"
    message = message_match.group(1) if message_match else ""
    traceback_text = traceback_match.group(1) if traceback_match else ""
    file_path = file_match.group(1) if file_match else ""
    line_num = int(line_match.group(1)) if line_match else 0

    print(f"File: {file_path}")
    print(f"Line: {line_num}")

    # Use Intelligence Engine
    intel = get_intelligence() if get_intelligence else None
    if intel:
        analysis = intel.analyze(error_type, message, traceback_text)
        if analysis:
            print(f"Pattern: {analysis.get('pattern', 'unknown')}")
            print(f"Confidence: {analysis.get('confidence', 0)}")
            print(f"Severity: {analysis.get('severity', 'unknown')}")

            fix_code = intel.generate_fix_code(analysis, file_path, line_num)
            with open("/tmp/fix_code.py", "w") as f:
                f.write(fix_code)
            print("Fix generated successfully")
            return 0

    # Fallback to OpenAI
    try:
        import openai

        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        prompt = (
            f"Fix this Python error:\n"
            f"Error: {error_type}: {message}\n"
            f"File: {file_path}:{line_num}\n"
            f"Traceback: {traceback_text[:2000]}\n\n"
            f"Provide only the fixed code section."
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        fix_code = response.choices[0].message.content
        with open("/tmp/fix_code.py", "w") as f:
            f.write(fix_code)
        print("OpenAI fix generated")
    except Exception as e:
        print(f"OpenAI fallback failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
