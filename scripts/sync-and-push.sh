#!/usr/bin/env bash
# sync-and-push.sh — Copy new .md from Hermes cron output, commit & push to GitHub
# Uses SSH key for authentication (no token needed, never expires)
# Silent when nothing new (cronjob delivers nothing to Telegram)
# Prints summary only when new files are pushed

set -euo pipefail

REPO_DIR="C:/Users/lognx/Documents/lognxtr/dhamma-quotes"
CRON_SRC="$HOME/AppData/Local/hermes/cron/output/8fd3ee00decc"
CRON_DST="$REPO_DIR/cron-output"
SSH_KEY="$HOME/.ssh/cron_hermes"

export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -i $SSH_KEY"

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
