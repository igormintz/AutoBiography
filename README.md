# biography-bot

Personal Hebrew voice-biography Telegram bot.

Receive a Hebrew voice message, transcribe with `ivrit-ai/whisper-large-v3-turbo-ct2`
(or OpenAI Whisper on serverless), structure with OpenAI `gpt-4o-mini`,
persist to Postgres, reply in Hebrew with summary, tags, and follow-up
questions.

See [`personal_biography.md`](./personal_biography.md) for the full design.

## Quickstart (local)

```bash
# 1. install deps (uses .python-version → 3.12)
uv sync

# 2. env
cp .env.example .env
# fill in: TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, DATABASE_URL, etc.

# 3. start a local Postgres
docker run -d --name biography-pg \
  -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=biography \
  -p 5432:5432 postgres:16

# 4. migrate
uv run alembic upgrade head

# 5. run
uv run uvicorn app.main:app --reload --port 8080

# 6. expose for Telegram
ngrok http 8080
# set BASE_URL in .env to the https URL, then:
./scripts/set_webhook.sh
```

## Tests

```bash
uv run pytest -q
uv run ruff format .
uv run ruff check .
```

## Deployment

### Option A: Railway / Docker (long-running server, full ML stack)

Build via the included `Dockerfile`. The image installs the `ml` extra so
`faster-whisper` runs in-process and the ivrit-ai model can be cached on
disk. Background loops (`retry_pending_loop`, `daily_digest_loop`) are
started by the FastAPI lifespan. See `personal_biography.md` §12.

### Option B: Vercel (serverless)

Vercel can serve the FastAPI app via the Python runtime. A few things
change automatically when `VERCEL=1` is set in the environment
(`Settings.is_serverless` becomes True):

- The lifespan **skips background loops** — they'd block the function
  forever and hit the timeout.
- `app.pipeline.transcribe` **falls back to OpenAI Whisper API**
  (`whisper-1`) because `faster-whisper` and the ivrit-ai weights are too
  large for the Vercel bundle.
- `LocalStore` **redirects writes under `/tmp`** since the rest of the
  filesystem is read-only. `/tmp` is per-invocation only — for durable
  storage rely on Postgres (or wire in S3/Drive).

Setup:

1. Push this repo to GitHub.
2. Go to [vercel.com/new](https://vercel.com/new) and import the repo.
   The `vercel.json` and `api/index.py` files configure the runtime
   automatically.
3. In Project Settings → Environment Variables, set:

   | Variable | Required | Notes |
   | --- | --- | --- |
   | `TELEGRAM_BOT_TOKEN` | yes | from @BotFather |
   | `TELEGRAM_WEBHOOK_SECRET` | yes | random ≥32 chars |
   | `ALLOWED_TG_USER_IDS` | yes | comma-separated user ids |
   | `OPENAI_API_KEY` | yes | used for both structuring and Whisper fallback |
   | `OPENAI_MODEL` | no | default `gpt-4o-mini` |
   | `OPENAI_WHISPER_MODEL` | no | default `whisper-1` |
   | `DATABASE_URL` | yes | `postgresql+asyncpg://...` (Neon, Supabase, Vercel Postgres, …) |
   | `CRON_SECRET` | yes | guards `/api/cron/*`; Vercel Cron sends it in the `Authorization` header |
   | `BASE_URL` | yes | the Vercel deployment URL — used to register the Telegram webhook |
   | `LOG_FORMAT` | no | `json` recommended in prod |

4. Deploy. After the first deploy, run the DB migration **once** from
   your local machine against the production DB:

   ```bash
   DATABASE_URL=<prod-url> uv run alembic upgrade head
   ```

5. Register the webhook:

   ```bash
   BASE_URL=<your-vercel-url> ./scripts/set_webhook.sh
   ```

6. The two cron jobs declared in `vercel.json` run automatically.
   Vercel's **Hobby plan only allows daily crons**, so both run once a
   day in UTC:

   - `/api/cron/retry-pending` daily at 03:00 UTC — re-runs structuring
     on entries flagged `needs_structuring`.
   - `/api/cron/daily-digest` daily at 06:00 UTC (≈ 09:00 Asia/Jerusalem;
     shifts by an hour during DST).

   On the **Pro plan** you can tighten `retry-pending` to e.g.
   `*/30 * * * *` for sub-daily retries.

#### Pulling production data back to your laptop

On Vercel the `LocalStore` writes to `/tmp`, which is per-invocation only —
the durable copy of every entry lives in Postgres. To get a local mirror of
production in the same `biography_output/` layout the live pipeline writes
locally:

```bash
DATABASE_URL=<prod-asyncpg-url> \
    uv run python scripts/dump_from_db.py --output-dir ./prod_dump
```

This produces `prod_dump/text/<short_id>.txt` (raw transcripts) and
`prod_dump/entries/<short_id>.json` (structured payloads). Re-run any time
to refresh the snapshot.

#### Known limits on Vercel

- **No GPU, no `faster-whisper`.** Hebrew transcription quality drops
  somewhat compared to ivrit-ai's fine-tuned model. If quality matters,
  keep the Railway/Docker deployment for transcription and use Vercel
  only as a frontend/webhook bridge.
- **No persistent filesystem.** Anything written under `OUTPUT_DIR`
  outside of `/tmp` will fail. Use Postgres / S3 / Drive for durability.
- **Cold starts.** First request after idle takes a few seconds while
  Postgres + Telegram client initialize.
- **60s function timeout.** Long voice messages whose transcription
  exceeds this will fail. Consider chunking or moving heavy work to a
  queue if needed.

### Option C: hybrid

Run the heavy transcription pipeline on Railway/Docker (with GPU + the
ivrit-ai model), and use Vercel only for the public Telegram webhook +
cron endpoints. Both speak to the same Postgres.
