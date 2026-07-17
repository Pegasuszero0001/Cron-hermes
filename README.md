# Cron-hermes

ธรรมะประจำวัน — Single-page web app aggregating Buddhist dhamma quotes from Hermes cron jobs.

## Live Site

https://pegasuszero0001.github.io/Cron-hermes/

## Architecture

```
Hermes Cronjob (.md output) → cron-output/ → GitHub Actions → quotes.json → index.html (fetch)
```

## Directory Structure

- `index.html` — Single-page web app (HTML5 + Vanilla JS)
- `quotes.json` — Aggregated quotes data (auto-generated)
- `scripts/quotes-ingest.py` — Parse .md files into quotes.json
- `cron-output/` — Raw cron job markdown outputs
- `.github/workflows/ingest-quotes.yml` — Auto-ingest every 4 hours

## Manual Workflow

1. Copy new `.md` files from Hermes cron output to `cron-output/`
2. Push to `main` — GitHub Actions will run automatically
3. Actions ingests new quotes → commits `quotes.json` → Pages auto-deploys

## Manual Local Run

```bash
python scripts/quotes-ingest.py
```
