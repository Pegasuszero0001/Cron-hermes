#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quote Ingest Script for Cronjob
-------------------------------
Reads markdown output files from Hermes cronjob and merges them into quotes.json.
Designed to run silently when nothing new; prints summary when new quotes added.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ═══ Configuration ═══
# CRON_OUTPUT_DIR: read from env (GitHub Actions) or default to local Hermes path
CRON_OUTPUT_DIR = Path(os.environ.get("CRON_OUTPUT_DIR", str(Path.home() / "AppData/Local/hermes/cron/output/8fd3ee00decc")))
QUOTES_JSON = Path(__file__).resolve().parent.parent / "quotes.json"
REPO_DIR = QUOTES_JSON.parent

# Git remote URL is configured via the cron job environment or existing git remote
# If none is set, push will be skipped.
ENABLE_GIT_PUSH = os.environ.get("QUOTES_ENABLE_GIT_PUSH", "true").lower() in ("1", "true", "yes")

# GitHub Actions workflow path
WORKFLOW_DIR = REPO_DIR / ".github" / "workflows"

# Map keywords to categories
CATEGORY_MAP = [
    ("อิทธิบาท", "อิทธิบาท"),
    ("อัปปมาท", "อัปปมาท"),
    ("ไม่ประมาท", "อัปปมาท"),
    ("หิริโอตตัปปะ", "หิริโอตตัปปะ"),
    ("สติ", "สติ"),
    ("สติปัฏฐาน", "สติ"),
    ("สมาธิ", "สมาธิ"),
    ("จิต", "จิต"),
    ("เจตนา", "กรรม"),
    ("กรรม", "กรรม"),
    ("กัมมัสสกตา", "กรรม"),
    ("ปัญญา", "ปัญญา"),
    ("วิริยะ", "วิริยะ"),
    ("ความเพียร", "วิริยะ"),
    ("เมตตา", "เมตตา"),
    ("มุทิตา", "มุทิตา"),
    ("กรุณา", "กรุณา"),
    ("อุเบกขา", "อุเบกขา"),
    ("ขันติ", "ขันติ"),
    ("โทสะ", "โทสะ"),
    ("ตัณหา", "ตัณหา"),
    ("ทุกข์", "ทุกข์"),
    ("อนิจจัง", "อนิจจัง"),
    ("อนัตตา", "อนัตตา"),
    ("สัจจะ", "สัจจะ"),
    ("กาลามสูตร", "กาลามสูตร"),
    ("สมาธิ", "สมาธิ"),
    ("ปฐมฌาน", "สมาธิ"),
    ("ราหุโลวาท", "สติ"),
]


def parse_created_at(filename: str) -> str:
    """Convert '2026-07-17_13-42-58.md' to ISO 8601 with +07:00."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.md", filename)
    if not m:
        return ""
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}+07:00"


def extract_blockquote(response_text: str) -> tuple[str, str]:
    """Extract first blockquote and source line."""
    lines = response_text.splitlines()
    quote_lines = []
    source = ""
    in_quote = False

    for i, line in enumerate(lines):
        if line.strip().startswith(">"):
            in_quote = True
            quote_lines.append(re.sub(r"^>\s?", "", line).strip())
        elif in_quote:
            # Source often follows blockquote immediately as '— source'
            clean = line.strip().lstrip("-—– ").strip()
            if clean and not clean.startswith("**"):
                source = clean.replace("**", "").strip()
                break
            elif quote_lines and not line.strip():
                continue
            elif quote_lines:
                break

    quote = " ".join(ql.strip() for ql in quote_lines if ql.strip())
    return quote, source


def extract_explanation(response_text: str, quote: str) -> str:
    """Extract explanation paragraphs after blockquote, excluding metadata."""
    lines = response_text.splitlines()
    after_quote = False
    paragraphs = []
    current_para = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            after_quote = True
            continue
        if not after_quote:
            continue
        if not stripped:
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
            continue
        # Skip source line, emoji-only lines, sign-off
        if re.match(r"^[-—–]\s*", stripped):
            continue
        if stripped.startswith("ด้วยความปรารถนาดี"):
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            continue
        # Remove markdown bold but keep text
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        # Remove emoji
        cleaned = re.sub(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF]", "", cleaned)
        if cleaned.strip():
            current_para.append(cleaned.strip())

    if current_para:
        paragraphs.append(" ".join(current_para))

    # Filter out paragraphs that are too short or duplicate quote
    valid = [p for p in paragraphs if len(p) > 30 and p != quote]
    return valid[0] if valid else ""


def detect_category(text: str) -> str:
    """Detect category from content keywords."""
    text_lower = text.lower()
    for keyword, category in CATEGORY_MAP:
        if keyword in text_lower:
            return category
    return "ธรรมทั่วไป"


def parse_markdown_file(md_path: Path) -> dict | None:
    """Parse a single cronjob markdown file into quote object."""
    content = md_path.read_text(encoding="utf-8")

    # Skip FAILED runs
    if "(FAILED)" in content or "## Error" in content:
        return None

    # Extract Response section
    match = re.search(r"## Response\s*\n+(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not match:
        return None

    response_text = match.group(1).strip()
    if not response_text:
        return None

    quote, source = extract_blockquote(response_text)
    if not quote:
        return None

    explanation = extract_explanation(response_text, quote)
    category = detect_category(response_text)
    created_at = parse_created_at(md_path.name)

    return {
        "id": f"quote-{md_path.stem}",  # unique per file
        "quote": quote,
        "explanation": explanation,
        "source": source or category,
        "category": category,
        "createdAt": created_at,
    }


def load_existing_quotes() -> tuple[list, set]:
    """Load existing quotes.json and return list + set of ids."""
    if not QUOTES_JSON.exists():
        return [], set()
    try:
        data = json.loads(QUOTES_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "quotes" in data:
            quotes = data["quotes"]
        elif isinstance(data, list):
            quotes = data
        else:
            quotes = []
        ids = {q.get("id") for q in quotes if q.get("id")}
        return quotes, ids
    except (json.JSONDecodeError, OSError):
        return [], set()


def main():
    if not CRON_OUTPUT_DIR.exists():
        # Silent fail if source dir missing
        sys.exit(0)

    quotes, existing_ids = load_existing_quotes()
    added = []

    md_files = sorted(CRON_OUTPUT_DIR.glob("*.md"))
    for md_path in md_files:
        q = parse_markdown_file(md_path)
        if not q:
            continue
        if q["id"] in existing_ids:
            continue
        quotes.append(q)
        added.append(q["id"])
        existing_ids.add(q["id"])

    if not added:
        # Silent: cronjob delivers nothing
        sys.exit(0)

    # Sort by createdAt descending
    quotes.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

    # Reassign sequential ids after sorting
    quotes = [{**q, "id": f"quote-{i+1:03d}"} for i, q in enumerate(reversed(quotes))]
    quotes.reverse()

    output = {
        "quotes": quotes,
        "updatedAt": datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=7))).isoformat(),
    }

    QUOTES_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pushed = False
    if ENABLE_GIT_PUSH:
        pushed = push_to_github(len(added))

    # Print summary for Telegram delivery
    if pushed:
        print(f"พบ quote ใหม่ {len(added)} รายการ รวม {len(quotes)} รายการ และ push ขึ้น GitHub แล้ว")
    else:
        print(f"พบ quote ใหม่ {len(added)} รายการ รวม {len(quotes)} รายกาใน quotes.json (Git push ถูกข้าม/ปิดใช้)")


def push_to_github(added_count: int) -> bool:
    """Commit and push quotes.json to the configured Git remote."""
    try:
        # Ensure git repo exists
        if not (REPO_DIR / ".git").is_dir():
            print("ไม่พบ git repository ใน {REPO_DIR}", file=sys.stderr)
            return False

        # Check remote
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print("ไม่มี git remote origin", file=sys.stderr)
            return False

        # Stage quotes.json
        subprocess.run(
            ["git", "add", "quotes.json"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
        )

        # Check if there's anything to commit
        status = subprocess.run(
            ["git", "status", "--porcelain", "quotes.json"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        if not status.stdout.strip():
            # Nothing changed
            return True

        # Commit
        timestamp = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"chore: update quotes.json (+{added_count}) at {timestamp}"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
        )

        # Push
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Git push failed: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode("utf-8", errors="ignore"), file=sys.stderr)
        return False
    except Exception as e:
        print(f"Unexpected error during git push: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    main()
