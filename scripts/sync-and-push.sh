#!/usr/bin/env bash
# sync-and-push.sh — Copy new .md from Hermes cron output, commit & push to GitHub
# Uses SSH key for authentication (no token needed, never expires)
# Silent when nothing new (cronjob delivers nothing to Telegram)
# Prints summary only when new files are pushed

set -euo pipefail

REPO_DIR="C:/Users/lognx/Documents/lognxtr/dhamma-quotes"
CRON_BASE="$HOME/AppData/Local/hermes/cron/output"
SSH_KEY="$HOME/.ssh/cron_hermes"

export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -i $SSH_KEY"

# Dynamically find the "Quote ธรรมะ" job's output dir by matching the cron job name
# (in case the job_id changes — e.g., when re-creating with a new provider).
QUOTE_JOB_ID=""
for d in "$CRON_BASE"/*/; do
  jid=$(basename "$d")
  # Look up the job name from jobs.json
  name=$(python -c "import json; d=json.load(open(r'C:\Users\lognx\AppData\Local\hermes\cron\jobs.json',encoding='utf-8')); [print(j['name']) for j in d.get('jobs',[]) if j.get('id')=='$jid']" 2>/dev/null)
  if [ "$name" = "Quote ธรรมะ" ]; then
    QUOTE_JOB_ID="$jid"
    break
  fi
done

if [ -z "$QUOTE_JOB_ID" ]; then
  echo "Could not find Quote ธรรมะ job dir under $CRON_BASE" >&2
  exit 0
fi

CRON_SRC="$CRON_BASE/$QUOTE_JOB_ID"
CRON_DST="$REPO_DIR/cron-output"
echo "Using quote job dir: $QUOTE_JOB_ID" >&2

# Check source dir exists
if [ ! -d "$CRON_SRC" ]; then
  echo "Source dir not found: $CRON_SRC" >&2
  exit 0  # silent fail
fi

cd "$REPO_DIR"

# Sync new .md files (only copy if different)
NEW_FILES=0
for md in "$CRON_SRC"/*.md; do
  [ -f "$md" ] || continue
  fname=$(basename "$md")
  if [ ! -f "$CRON_DST/$fname" ] || ! diff -q "$md" "$CRON_DST/$fname" > /dev/null 2>&1; then
    cp "$md" "$CRON_DST/$fname"
    NEW_FILES=$((NEW_FILES + 1))
  fi
done

if [ $NEW_FILES -eq 0 ]; then
  # Nothing new — silent (cronjob delivers nothing)
  exit 0
fi

# Pull remote changes first (GitHub Actions may have pushed quotes.json)
git pull --rebase origin main 2>/dev/null || true

# Stage and commit
git add cron-output/
git commit -m "sync: $NEW_FILES new cron output file(s) from Hermes" 2>/dev/null

# Push (remote URL already has token embedded)
if git push origin main 2>/dev/null; then
  echo "🪷 ส่ง $NEW_FILES ไฟล์ใหม่ขึ้น GitHub แล้ว — GitHub Actions จะอัปเดต quotes.json อัตโนมัติ"
else
  echo "⚠️ พบ $NEW_FILES ไฟล์ใหม่ แต่ push ไม่สำเร็จ (ลองใหม่รอบหน้า)" >&2
  exit 1
fi
