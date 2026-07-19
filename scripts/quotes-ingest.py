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
    """Extract first blockquote and source line.

    Source lookup order:
    1. Last blockquote line starting with — or -- or –
    2. Embedded '—' in last blockquote line (inline source)
    3. Text before blockquote mentioning 'พุทธ' / 'ตรัส' / 'สูตร'
    4. Fallback: last body line that looks like a citation

    Returns (quote_text, source_reference).
    """
    lines = response_text.splitlines()
    quote_lines = []
    pre_lines = []
    in_quote = False

    for line in lines:
        if line.strip().startswith(">"):
            in_quote = True
            quote_lines.append(re.sub(r"^>\s?", "", line).strip())
        elif not in_quote:
            pre_lines.append(line.strip())
        else:
            break

    if not quote_lines:
        return "", ""

    # ── Step 1: Find source in blockquote (last line starting with —/--/–)
    source_idx = -1
    source = ""
    citation_check_kw = ("พระ", "พุทธ", "ตรัส", "สูตร", "นิกาย", "ปิฎก", "เล่ม", "ข้อ", "น.", "Dhammapada", "AN", "SN", "MN", "องฺ", "สํ", "ขุ", "ที", "ม.", "อภิ")
    for i in range(len(quote_lines) - 1, -1, -1):
        stripped = quote_lines[i].strip()
        if any(stripped.startswith(d) for d in ("\u2014", "--", "\u2013")):
            candidate = re.sub(r"^[\u2014\u2013-]{1,2}\s*", "", stripped).strip()
            candidate = re.sub(r"\*\*(.+?)\*\*", r"\1", candidate)
            # Only accept if it looks like a citation (short or has citation keywords)
            if len(candidate) <= 30 or any(kw in candidate for kw in citation_check_kw):
                source = candidate
                source_idx = i
            break

    body_lines = [l for j, l in enumerate(quote_lines) if j != source_idx]

    # ── Step 1b: First line of blockquote may be a lead-in with source
    # (e.g. "พระพุทธเจ้าตรัสไว้ในอังคุตตรนิกายว่า")
    if body_lines and not source:
        first = re.sub(r"\*\*(.+?)\*\*", r"\1", body_lines[0])  # strip bold
        pre_patterns = [
            r"(?:พระพุทธเจ้า|พระผู้มีพระภาค)(?:ตรัส|กล่าว|สอน)(?:ไว้ใน|ใน)(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ในพระไตรปิฎก(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ในคัมภีร์(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
        ]
        for pat in pre_patterns:
            m = re.search(pat, first)
            if m:
                candidate = m.group(1).strip()
                if len(candidate) > 2:
                    source = candidate
                    # Remove lead-in from body if it matches well
                    if first in (m.group(0),) or len(m.group(0)) > 15:
                        body_lines.pop(0)
                    break

    # ── Step 2: If no explicit dash source, look for embedded '—' in last line only
    if not source and body_lines:
        idx = len(body_lines) - 1
        line = body_lines[idx]
        sep_match = re.search(r"\s[\u2014\u2013-]{1,2}\s(.+)$", line)
        if sep_match:
            candidate = sep_match.group(1).strip()
            before_sep = line[:sep_match.start()].strip()
            # Accept only if part after separator looks like a citation
            citation_kw = ("พระ", "พุทธ", "ตรัส", "สูตร", "นิกาย", "ปิฎก", "เล่ม", "ข้อ", "น.", "Dhammapada")
            is_citation = any(kw in candidate for kw in citation_kw)
            # Or if the part BEFORE looks like a lead-in (has teaching verbs)
            is_leadin = any(kw in before_sep for kw in ("พุทธ", "ตรัส", "กล่าว", "สอน"))
            if is_citation or (is_leadin and len(candidate) > 5):
                # Try to extract just the citation from parentheses if candidate is long
                paren_match = re.search(r'\((.+?)\)\s*$', candidate)
                if paren_match and len(candidate) > 30:
                    candidate = paren_match.group(1).strip()
                source = candidate
                body_lines[idx] = before_sep
                source = re.sub(r"\*\*(.+?)\*\*", r"\1", source)

    # ── Step 3: Look for source mention in text BEFORE blockquote
    if not source and pre_lines:
        pre_text = " ".join(pre_lines)
        # Strip markdown bold for easier matching
        pre_text_clean = re.sub(r"\*\*(.+?)\*\*", r"\1", pre_text)
        pre_text_clean = re.sub(r"\s+", " ", pre_text_clean)  # normalize spaces
        # Look for patterns like "พุทธวจนะในXXX", "XXXสูตร", "พระพุทธเจ้าตรัสในXXX"
        source_patterns = [
            r"พุทธวจนะใน(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ใน(.+(?:สูตร|นิกาย|ปิฎก))",
            r"ตรัสไว้ใน(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ตรัสสอน(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"พระพุทธเจ้าตรัสไว้ใน(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ในคัมภีร์(.+?)(?:\s*พระ|\s*ว่า|\s*[,\(\)]|\s*$)",
            r"ที่ชื่อว่า(.+?)(?:สูตร|นิกาย|ปิฎก)",
            r"พระพุทธเจ้าทรงสอนไว้ใน(.+?)(?:\s*ว่า|\s*[,\(\)]|\s*$)",
        ]
        for pat in source_patterns:
            m = re.search(pat, pre_text_clean)
            if m:
                candidate = m.group(1).strip()
                # Clean up incomplete parentheticals
                if candidate.count("(") > candidate.count(")"):
                    last_open = candidate.rfind("(")
                    if last_open >= 0:
                        candidate = candidate[:last_open].strip()
                candidate = candidate.rstrip("(")
                if len(candidate) > 2:
                    source = candidate
                    break

    # ── Step 4: Fallback — last body line looks like a citation
    if not source and body_lines:
        last_line = body_lines[-1]
        citation_keywords = ("พระ", "พุทธ", "ตรัส", "สูตร", "นิกาย", "ปิฎก", "เล่ม", "ข้อ", "น.")
        if any(kw in last_line for kw in citation_keywords):
            source = body_lines.pop()
            source = re.sub(r"\*\*(.+?)\*\*", r"\1", source)

    quote = " ".join(ql.strip() for ql in body_lines if ql.strip())
    quote = re.sub(r"\*\*(.+?)\*\*", r"\1", quote).strip()
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
        # Skip lines that are just metadata/sign-off/separator
        if re.match(r"^[-—–]{2,}\s*$", stripped):
            continue
        if re.match(r"^[-—–]\s*", stripped) and any(kw in stripped for kw in [
            "ด้วยความปรารถนาดี", "มาเบลล์", "เลขา", "คุณนอร์ท", "🙏", "✨", "🌿", "🌟", "💪"
        ]):
            continue
        if stripped.startswith("ด้วยความปรารถนาดี"):
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            continue
        # Remove markdown bold but keep text
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        # Remove emoji at start/end
        cleaned = re.sub(
            r"^[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF\U0001F600-\U0001F64F]+"
            r"|[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF\U0001F600-\U0001F64F]+$",
            "", cleaned
        ).strip()
        if cleaned:
            current_para.append(cleaned)

    if current_para:
        paragraphs.append(" ".join(current_para))

    # Filter out paragraphs that are too short, duplicate quote, or look like sign-off
    valid = [p for p in paragraphs if len(p) > 20 and p != quote
             and not p.startswith("ด้วยความปรารถนาดี")]
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


def load_existing_quotes() -> tuple[list, set, set]:
    """Load existing quotes.json and return list + set of ids + set of quote texts."""
    if not QUOTES_JSON.exists():
        return [], set(), set()
    try:
        data = json.loads(QUOTES_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "quotes" in data:
            quotes = data["quotes"]
        elif isinstance(data, list):
            quotes = data
        else:
            quotes = []
        ids = {q.get("id") for q in quotes if q.get("id")}
        texts = {q.get("quote") for q in quotes if q.get("quote")}
        return quotes, ids, texts
    except (json.JSONDecodeError, OSError):
        return [], set(), set()


def main():
    if not CRON_OUTPUT_DIR.exists():
        # Silent fail if source dir missing
        sys.exit(0)

    quotes, existing_ids, existing_texts = load_existing_quotes()
    added = []

    md_files = sorted(CRON_OUTPUT_DIR.glob("*.md"))
    for md_path in md_files:
        q = parse_markdown_file(md_path)
        if not q:
            continue
        # Dedup by both filename-based ID and quote text content
        if q["id"] in existing_ids:
            continue
        if q["quote"] in existing_texts:
            continue
        quotes.append(q)
        added.append(q["id"])
        existing_ids.add(q["id"])
        existing_texts.add(q["quote"])

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
