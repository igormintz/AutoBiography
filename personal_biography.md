# Personal Voice Biography Bot — Detailed Build Plan

A personal Telegram bot that turns Hebrew voice notes into a structured,
queryable autobiographical database, ready for later biography generation.

---

## 0. Decision Log

Every architecture and product choice, locked in.

| Area | Decision |
| --- | --- |
| Client | Telegram bot (single user for MVP) |
| Backend | FastAPI on Railway, async, webhook mode |
| Transcription model | [`ivrit-ai/whisper-large-v3-turbo-ct2`](https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2) |
| Transcription runtime | `faster-whisper` (CTranslate2), `int8` on CPU, GPU-ready via env |
| Structuring LLM | OpenAI `gpt-4o-mini` |
| Bot reply language | Hebrew only |
| Bot tone | Neutral, clear (modern Hebrew, no slang, no high register) |
| Bot reply contents | Full bundle: transcript + 1-line summary + tags + 3–5 follow-up questions + entry ID |
| Tag vocabulary | Fixed list of 10 (see §7) |
| Follow-up answers | New child entry with `parent_id` |
| Audio retention | Deleted immediately after transcription |
| Mistranscription fix | `/edit <id>` command |
| `importance_score` | Dropped for MVP |
| Storage | Postgres on Railway (primary) + Google Drive (JSON + transcript copies) |
| Drive auth | Service account |
| Background jobs | `asyncio.create_task`, in-process |
| LLM failure handling | Retry 3×, save raw with `needs_structuring` flag, background retry |
| User scope | Single user via `ALLOWED_TG_USER_IDS` env var |
| Voice length | Up to 10 minutes |
| Text messages | Accepted (bypass transcription, go straight to structuring) |
| Entity storage | String array per entry for MVP; no normalized entities table yet |
| Cost control | Soft cap: daily usage DM (no hard cutoff) |
| Python tooling | `uv` (per CLAUDE.md) |
| Data layer | SQLModel + Alembic |
| Telegram lib | `python-telegram-bot` v21+ |
| Repo | Local-only at `/Users/igor/Documents/personal_biography`, push to GitHub later |
| Deployment | Railway (`railway.com`), single service for MVP |

---

## 1. Goal

Build a Telegram bot that:

* Receives Hebrew voice messages (or typed text)
* Transcribes via `ivrit-ai/whisper-large-v3-turbo-ct2`
* Structures the transcript into JSON via OpenAI `gpt-4o-mini`
* Persists everything to Postgres + Google Drive
* Replies in Hebrew with the transcript, summary, tags, follow-up questions, and entry ID
* Lets me correct, restructure, search, and link entries via slash commands
* Runs cheaply on Railway

---

## 2. High-Level Architecture

```
   ┌────────────┐      voice / text      ┌──────────────────────┐
   │  Telegram  │ ─────────────────────▶ │  /telegram/webhook   │
   │   client   │ ◀──── Hebrew reply ─── │       (FastAPI)      │
   └────────────┘                        └──────────┬───────────┘
                                                    │ asyncio.create_task
                                ┌───────────────────┼──────────────────────┐
                                ▼                   ▼                      ▼
                       ┌────────────────┐  ┌────────────────┐    ┌──────────────────┐
                       │ faster-whisper │  │  OpenAI 4o-mini│    │  DriveStore      │
                       │  (Hebrew STT)  │  │  (structuring) │    │  (gdrive client) │
                       └───────┬────────┘  └───────┬────────┘    └────────┬─────────┘
                               │                   │                       │
                               └────────┬──────────┴───────────────────────┘
                                        ▼
                                ┌────────────────┐
                                │ Postgres (Rail-│
                                │ way) — primary │
                                └────────────────┘
```

* Webhook returns `200 OK` immediately after persisting the raw incoming
  message and scheduling background work.
* Drive holds a durable copy of the structured JSON and the transcript.
* Audio is **never persisted** — it's downloaded into memory, transcribed,
  and discarded.

---

## 3. Stack & Versions

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.11 | Matches Railway's default Python image |
| Package manager | `uv` | Per `CLAUDE.md`; Dockerfile uses `uv sync` |
| Web framework | `FastAPI` ≥ 0.110 | Async; ASGI |
| ASGI server | `uvicorn` | Single process, `--workers 1` (in-memory queue) |
| Telegram lib | `python-telegram-bot` ≥ 21 | Webhook mode |
| Transcription | `faster-whisper` ≥ 1.1 | CTranslate2 backend |
| Model | `ivrit-ai/whisper-large-v3-turbo-ct2` | Pulled from HF on first run |
| LLM | `openai` ≥ 1.40 | `gpt-4o-mini` |
| ORM | `sqlmodel` ≥ 0.0.22 | + `sqlalchemy[asyncio]` |
| Migrations | `alembic` | Auto-generate from SQLModel |
| DB driver | `asyncpg` | Async Postgres |
| Drive | `google-api-python-client` + `google-auth` | Service account |
| Audio decoding | `ffmpeg` (system) | Required by `faster-whisper` |
| Validation | `pydantic` v2 | Comes with FastAPI/SQLModel |
| Logging | `structlog` | Structured JSON logs for Railway |
| Lint/format | `ruff` | Per `CLAUDE.md` |
| Tests | `pytest`, `pytest-asyncio`, `httpx` | Per `CLAUDE.md` TDD |

---

## 4. Telegram Bot Spec

### 4.1 Commands

| Command | Purpose |
| --- | --- |
| `/start` | Greets, confirms allowlist, prints help |
| `/help` | Lists commands |
| `/last` | Returns the last entry's summary + tags |
| `/show <id>` | Returns full transcript + structured fields |
| `/edit <id>` | Bot replies with current transcript; user sends corrected text → re-structures |
| `/restructure <id>` | Re-runs LLM on existing transcript (e.g. after prompt tweak) |
| `/tags <id>` | Returns tags only; reply with comma-separated list to overwrite |
| `/questions` | Re-sends the last set of follow-up questions |
| `/usage` | Today's tokens + transcription seconds + estimated $ |
| `/search <text>` | Postgres ILIKE over transcripts; returns up to 5 matches |

### 4.2 Voice message flow

1. User sends `voice` message.
2. Webhook validates `update.effective_user.id ∈ ALLOWED_TG_USER_IDS`.
3. Bot replies: `מקבל ומתמלל…` (≈ "received and transcribing…").
4. Backend downloads audio via `Bot.get_file()` (Telegram URL valid ~1h).
5. `asyncio.create_task` runs the pipeline:
   1. Transcribe (in-process).
   2. Structure via OpenAI.
   3. Persist to Postgres.
   4. Push transcript + JSON to Drive.
   5. Edit the original "מקבל ומתמלל…" reply with the full bundle.
6. Audio bytes are dropped on function exit. Nothing about the audio is
   written to disk.

### 4.3 Text message flow

If the message is plain text (not a command, not a voice):

* Skip transcription.
* Treat the text as the transcript.
* Run the same structuring + persistence + Drive flow.
* Reply with the same full bundle (with no "transcript" preamble since it's
  the user's own text).

### 4.4 Reply format (Hebrew, neutral tone)

```
📝 התמליל
{transcript}

📌 תקציר
{summary}

🏷 תגיות: {tag1, tag2, ...}

❓ שאלות המשך:
1. {q1}
2. {q2}
3. {q3}

🆔 {short_id}
```

For `/edit` flows the bot replies with just the new transcript + ID.

### 4.5 Authorization

* `ALLOWED_TG_USER_IDS=123456789` (single ID for now, comma-separated for future).
* Any other sender gets a single response: `הבוט הזה פרטי.` and the message is dropped.

---

## 5. Backend Project Layout

```
personal_biography/
├── pyproject.toml          # uv-managed
├── uv.lock
├── Dockerfile              # python:3.11-slim + ffmpeg
├── railway.toml            # build & deploy config
├── alembic.ini
├── README.md
├── .env.example
├── migrations/             # alembic
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI factory + webhook routes
│   ├── config.py           # Settings (pydantic-settings)
│   ├── logging.py          # structlog setup
│   ├── deps.py             # FastAPI dependencies (db session, settings)
│   ├── auth.py             # ALLOWED_TG_USER_IDS check
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── application.py  # python-telegram-bot Application setup
│   │   ├── handlers.py     # message + command handlers
│   │   └── replies.py      # Hebrew reply templates
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py # the async pipeline (transcribe→structure→persist→drive)
│   │   ├── transcribe.py   # faster-whisper wrapper
│   │   ├── structure.py    # OpenAI structuring + prompt
│   │   └── prompts.py      # prompt strings
│   ├── store/
│   │   ├── __init__.py
│   │   ├── models.py       # SQLModel tables
│   │   ├── repo.py         # CRUD helpers
│   │   └── drive.py        # DriveStore class
│   └── obs/
│       ├── __init__.py
│       └── usage.py        # daily usage tracking
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_handlers.py
│   ├── test_structure.py
│   ├── test_repo.py
│   └── fixtures/
│       └── sample_he.ogg   # short Hebrew clip for transcription tests
└── scripts/
    ├── set_webhook.sh      # registers Telegram webhook
    └── seed_local.py       # seeds local Postgres with a fake entry
```

---

## 6. Transcription

### 6.1 Model loading

```python
# app/pipeline/transcribe.py
from faster_whisper import WhisperModel
from app.config import settings

_model: WhisperModel | None = None

def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            "ivrit-ai/whisper-large-v3-turbo-ct2",
            device=settings.whisper_device,        # "cpu" or "cuda"
            compute_type=settings.whisper_compute, # "int8" or "float16"
            download_root=settings.hf_home,        # /data/hf-cache on Railway
        )
    return _model
```

* Model loaded **lazily** on first request — keeps cold-start fast on Railway.
* `download_root` points at the persistent volume so the multi-GB weights
  survive deploys.
* CPU default is `int8`; GPU default is `float16`. Both via env vars.

### 6.2 Transcribing

```python
def transcribe(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(audio_bytes)
        f.flush()
        segments, info = get_model().transcribe(
            f.name,
            language="he",
            vad_filter=True,
            beam_size=5,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
```

* `language="he"` is forced — no auto-detect (Whisper sometimes guesses Arabic).
* `vad_filter=True` removes long silences, speeds things up.
* Returns plain text. No timestamps in MVP.

### 6.3 Performance expectations

* `turbo-ct2` int8 on Railway Hobby (CPU): ~0.3–0.5× real-time
  → 10-min audio ≈ 20–30s of transcription.
* GPU (Pro): ~5× real-time → 10-min audio ≈ 2 minutes.
* These are estimates; benchmark in Phase 2 and revisit Railway plan choice.

---

## 7. LLM Structuring

### 7.1 Output schema (Pydantic, used as OpenAI `response_format`)

```python
from typing import Literal
from pydantic import BaseModel, Field

Tag = Literal[
    "childhood", "family", "school", "army", "career",
    "relationships", "health", "travel", "milestones", "daily_life",
]

class Timeline(BaseModel):
    approx_age: int | None = None
    year: int | None = None

class Structured(BaseModel):
    summary: str = Field(..., description="1–2 sentence Hebrew summary")
    tags: list[Tag] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list, description="people, places, events")
    timeline: Timeline = Field(default_factory=Timeline)
    follow_up_questions: list[str] = Field(..., min_length=3, max_length=5)
```

`importance_score` removed per the decision log.

### 7.2 Prompt (Hebrew-aware, English instructions for stability)

Stored at `app/pipeline/prompts.py`:

```text
You are helping build a structured Hebrew autobiography database.

Given a Hebrew transcript of a personal memory, produce JSON with:
- summary: 1–2 sentence Hebrew summary, neutral and concise
- tags: choose only from this fixed list:
  childhood, family, school, army, career, relationships, health, travel,
  milestones, daily_life
- entities: Hebrew names of people, places, and events mentioned in the
  transcript. Up to 10. Do not invent.
- timeline.approx_age: integer if implied, else null
- timeline.year: 4-digit year if explicit, else null
- follow_up_questions: 3–5 specific Hebrew questions that, if answered,
  would improve missing details, chronology, or significance. Avoid yes/no
  questions. Avoid generic prompts.

Do not invent facts. If a field is unknown, use null or an empty list.
Output Hebrew text in Hebrew. Output JSON keys in English.

Transcript:
"""
{transcript}
"""
```

### 7.3 Calling OpenAI

```python
# app/pipeline/structure.py
from openai import AsyncOpenAI
from app.pipeline.prompts import STRUCTURING_PROMPT
from app.store.models import Structured

client = AsyncOpenAI(api_key=settings.openai_api_key)

async def structure(transcript: str) -> Structured:
    resp = await client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": STRUCTURING_PROMPT.split("Transcript:")[0]},
            {"role": "user", "content": f'Transcript:\n"""\n{transcript}\n"""'},
        ],
        response_format=Structured,
        temperature=0.2,
    )
    return resp.choices[0].message.parsed
```

* Uses OpenAI's parsed structured-outputs API → guaranteed-valid JSON,
  no manual parsing.
* `temperature=0.2` for consistency.

### 7.4 Failure handling

```python
async def structure_with_retry(transcript: str) -> Structured | None:
    for attempt in range(3):
        try:
            return await structure(transcript)
        except (OpenAIError, ValidationError) as e:
            log.warning("structuring_failed", attempt=attempt, error=str(e))
            await asyncio.sleep(2 ** attempt)
    return None  # caller marks entry status=needs_structuring
```

A periodic `asyncio` task re-tries `needs_structuring` rows every 30 minutes.

---

## 8. Postgres Schema

Two tables for MVP. Owner is implicit (single user); add `user_id` later.

### 8.1 `entries`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `uuid` PK | Generated server-side |
| `short_id` | `text` UNIQUE | 6-char human-friendly (e.g. `K7M2QX`); used in commands |
| `created_at` | `timestamptz` | `default now()` |
| `source` | `text` | `'voice'` \| `'text'` |
| `parent_id` | `uuid` NULL FK→entries.id | Set when this entry answers a follow-up |
| `transcript` | `text` | Hebrew |
| `summary` | `text` NULL | Hebrew |
| `tags` | `text[]` | Validated against fixed vocabulary in app code |
| `entities` | `text[]` | Hebrew, up to 10 |
| `approx_age` | `int` NULL | |
| `year` | `int` NULL | |
| `follow_up_questions` | `text[]` | Hebrew |
| `status` | `text` | `'ok'` \| `'needs_structuring'` \| `'editing'` |
| `drive_json_id` | `text` NULL | Drive file ID for the JSON copy |
| `drive_text_id` | `text` NULL | Drive file ID for the transcript |
| `tg_message_id` | `bigint` NULL | Original Telegram message ID, for /edit replies |
| `tg_chat_id` | `bigint` NULL | |

Indexes: `created_at desc`, GIN on `tags`, GIN on `entities`,
trigram (`pg_trgm`) on `transcript` for `/search`.

### 8.2 `usage_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `bigserial` PK | |
| `created_at` | `timestamptz` | `default now()` |
| `kind` | `text` | `'transcribe'` \| `'structure'` |
| `seconds` | `numeric` NULL | For `transcribe` |
| `tokens_in` | `int` NULL | For `structure` |
| `tokens_out` | `int` NULL | For `structure` |
| `cost_usd` | `numeric(10,6)` | Computed at insert time |
| `entry_id` | `uuid` NULL FK→entries.id | |

Used by `/usage` and the daily DM digest.

### 8.3 Migrations

* `alembic init migrations`
* Initial migration: both tables + extensions (`pg_trgm`).
* Every model change → `alembic revision --autogenerate -m "..."`.
* Apply on Railway via `release` step (see §12).

---

## 9. Google Drive Storage

### 9.1 Folder layout

```
Voice Biography/
├── text/      # YYYY-MM-DD_HH-MM_<short_id>.txt   (transcript)
└── entries/   # YYYY-MM-DD_HH-MM_<short_id>.json  (structured)
```

No `audio/` folder — audio is deleted before this step.

### 9.2 Setup steps (one-time, runbook)

1. Create a Google Cloud project.
2. Enable Drive API.
3. Create a service account, download `service-account.json`.
4. In Drive, create folder "Voice Biography".
5. Share that folder with the service account email (Editor role).
6. Copy the folder ID from the URL → `GOOGLE_DRIVE_FOLDER_ID`.
7. Paste the JSON into Railway env as `GOOGLE_SERVICE_ACCOUNT_JSON`
   (raw JSON, single-line; we parse with `json.loads`).

### 9.3 `DriveStore` interface

```python
class DriveStore:
    def __init__(self, folder_id: str, sa_json: str) -> None: ...
    async def save_transcript(self, short_id: str, text: str) -> str: ...   # returns file ID
    async def save_entry_json(self, short_id: str, data: dict) -> str: ...  # returns file ID
```

* Subfolders (`text/`, `entries/`) are created lazily and cached by ID.
* Failures: log + raise. Caller decides whether to mark the entry's
  `drive_*_id` as null and queue for retry on a `/retry-drive` cron.

---

## 10. Background Processing

### 10.1 Pattern

```python
# in the Telegram handler
async def on_voice(update, context):
    if not is_allowed(update): return
    msg = await update.message.reply_text("מקבל ומתמלל…")
    audio = await download_voice(update)
    asyncio.create_task(
        run_pipeline(
            audio_bytes=audio,
            tg_chat_id=update.effective_chat.id,
            tg_message_id=msg.message_id,
        )
    )
```

* Webhook returns immediately; Telegram is happy.
* `run_pipeline` performs the steps, then edits `msg` with the final reply.

### 10.2 Caveats

* If the process restarts mid-pipeline, the in-flight job is lost — a
  `/retry-pending` admin command (Phase 6+) re-runs anything stuck in
  `needs_structuring`.
* For audio-only loss (no transcript yet), nothing can be done — audio is
  already discarded. The user resends.
* Single uvicorn worker (`--workers 1`) so the in-memory model is shared.

### 10.3 Periodic tasks

A single `asyncio.create_task` started in FastAPI's `lifespan`:

* Every 30 min: retry `needs_structuring` entries.
* Every day at 09:00 local (Asia/Jerusalem): send `/usage`-style DM.

---

## 11. Configuration / Env Vars

`app/config.py` (pydantic-settings):

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | — | From @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | yes | — | Random 32-char; appears in webhook URL |
| `ALLOWED_TG_USER_IDS` | yes | — | Comma-separated |
| `OPENAI_API_KEY` | yes | — | |
| `DATABASE_URL` | yes | — | Provided by Railway Postgres |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | yes | — | Raw JSON |
| `GOOGLE_DRIVE_FOLDER_ID` | yes | — | The "Voice Biography" folder |
| `WHISPER_DEVICE` | no | `cpu` | `cuda` if GPU |
| `WHISPER_COMPUTE` | no | `int8` | `float16` for GPU |
| `HF_HOME` | no | `/data/hf-cache` | Persistent volume mount |
| `LOG_LEVEL` | no | `INFO` | |
| `TIMEZONE` | no | `Asia/Jerusalem` | For daily digest scheduling |
| `BASE_URL` | yes | — | e.g. `https://biography.up.railway.app`, used for webhook setup |

`.env.example` checked in. `.env` gitignored.

---

## 12. Railway Deployment

### 12.1 Services

For MVP: **one service** (`biography-bot`) + **Railway Postgres add-on**.

### 12.2 `Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf-cache

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

### 12.3 `railway.toml`

```toml
[build]
builder = "DOCKERFILE"

[deploy]
startCommand = "uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
healthcheckPath = "/healthz"
restartPolicyType = "ON_FAILURE"

[deploy.release]
command = "uv run alembic upgrade head"
```

### 12.4 Volume

* Mount: `/data`
* Used for: HF cache only (`HF_HOME=/data/hf-cache`).
* Size: 8 GB is comfortable.

### 12.5 Webhook registration

After first successful deploy:

```bash
# scripts/set_webhook.sh
curl -fsSL -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${BASE_URL}/telegram/webhook/${TELEGRAM_WEBHOOK_SECRET}" \
  --data-urlencode "allowed_updates=[\"message\"]"
```

Telegram retries failed webhooks for ~24 h, so brief outages don't drop messages.

### 12.6 Plan sizing

* **Hobby ($5/mo)** is the default target: enough for `int8` CPU
  transcription on short-to-medium clips.
* If 10-min messages feel too slow, upgrade to a GPU plan and flip
  `WHISPER_DEVICE=cuda`, `WHISPER_COMPUTE=float16`. No code change.

---

## 13. Local Development

### 13.1 Prereqs

* Python 3.11
* `uv` (`brew install uv`)
* `ffmpeg` (`brew install ffmpeg`)
* Postgres 16 (Docker easiest):

  ```bash
  docker run -d --name biography-pg \
    -e POSTGRES_PASSWORD=dev -p 5432:5432 \
    postgres:16
  ```

### 13.2 Bootstrap

```bash
cd /Users/igor/Documents/personal_biography
uv sync
cp .env.example .env   # fill values
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8080
```

### 13.3 Exposing the webhook

```bash
ngrok http 8080
# copy the https URL → BASE_URL in .env
./scripts/set_webhook.sh
```

### 13.4 Tests

```bash
uv run pytest -q
uv run ruff format .
uv run ruff check .
```

Per `CLAUDE.md`: write tests before adding new functions; format on edit.

---

## 14. Testing Strategy

| Layer | What to test | How |
| --- | --- | --- |
| Auth | `is_allowed` allow/deny | Pure unit |
| Repo | Insert, fetch by short_id, search | Real Postgres in CI (Docker) |
| Structuring | Prompt produces valid `Structured` | Mock OpenAI client; assert pydantic parse |
| Transcribe | Loads model, transcribes a tiny Hebrew clip | One slow integration test, marked `@pytest.mark.slow` |
| Drive | `save_transcript` creates a file | Mock `google-api-python-client` |
| Handlers | Voice → reply text | Use `python-telegram-bot`'s `Application.builder().updater(None)` test mode |
| End-to-end | POST a fake Telegram update → 200 + entry persisted | `httpx.AsyncClient` against the FastAPI app |

Coverage target: 70% line, with all happy paths and explicit failure paths
covered. Skipped: model warm-up, real OpenAI calls, real Drive calls.

---

## 15. Reliability & Failure Modes

| Failure | Behavior |
| --- | --- |
| Webhook delivery fails | Telegram retries up to 24 h. Idempotency via `update_id` (cache last 1000 in memory). |
| Whisper crashes | Reply: `שגיאה בתמלול, נסה שוב.` Entry not persisted. Audio already gone. |
| OpenAI fails 3× | Entry persisted with `status='needs_structuring'`. Background retry every 30 min. User notified on success. |
| Drive fails | Entry still in Postgres (source of truth). `drive_*_id` left null. Retry on next `/usage` tick. |
| Postgres down | Webhook returns 500 → Telegram retries. Logged. |
| Telegram file URL expired (1h) | Should not happen — we download immediately. If it does, reply asks user to resend. |
| Process restart mid-pipeline | Audio-only loss is unrecoverable; `needs_structuring` entries auto-recover. |
| Daily-digest task crashes | Logged; resumes next day. Not critical. |

---

## 16. Cost & Observability

### 16.1 Cost model (rough)

* OpenAI `gpt-4o-mini`: ~$0.15 / 1M input + $0.60 / 1M output.
  10-min transcript ≈ 1.5K tokens in + 0.5K out → ~$0.0006 per memory.
* Whisper inference: ~free on Hobby (CPU time included in plan).
* Postgres + volume: included in $5/mo Hobby.
* **Estimated steady state: under $1/month for personal use.**

### 16.2 Daily digest

At 09:00 Asia/Jerusalem, bot DMs you:

```
📊 ‎ אתמול
• הודעות: 4
• דקות תמלול: 12.3
• טוקנים LLM: 6,210 (≈ $0.003)
• סה״כ עלות חודש מצטבר: $0.07
```

Numbers come from `usage_events`.

### 16.3 Logs

* `structlog` JSON to stdout → Railway captures.
* Key fields: `event`, `entry_id`, `short_id`, `tg_user_id`, `latency_ms`,
  `error`.

### 16.4 Health

* `GET /healthz` returns 200 if DB reachable + bot token configured.
* Railway uses it as healthcheck.

---

## 17. Build Phases

Concrete checklist. Each phase ends with something I can demo.

### Phase 0 — Repo bootstrap

- [ ] `uv init`, set Python 3.11, add deps from §3.
- [ ] Add `Dockerfile`, `railway.toml`, `.env.example`, `.gitignore`.
- [ ] Empty `app/` skeleton matching §5.
- [ ] `pytest` smoke test passes.

### Phase 1 — FastAPI skeleton + Postgres

- [ ] `GET /healthz` returns 200.
- [ ] `app/config.py` loads env vars.
- [ ] SQLModel models for `entries` + `usage_events`.
- [ ] `alembic init`, initial migration, `upgrade head` works locally.
- [ ] `repo.py` with `insert_entry`, `get_by_short_id`, `search_transcript`.
- [ ] Tests for repo + healthz.

### Phase 2 — Transcription, offline

- [ ] `transcribe.py` loads `ivrit-ai/whisper-large-v3-turbo-ct2`.
- [ ] CLI: `uv run python -m app.pipeline.transcribe <file.ogg>` prints text.
- [ ] One integration test on a short Hebrew sample.
- [ ] Benchmark a 5-min clip; record timing.

### Phase 3 — LLM structuring

- [ ] `prompts.py` finalized.
- [ ] `structure.py` returns `Structured`.
- [ ] Unit tests with mocked OpenAI.
- [ ] Manual: feed yesterday's transcript, eyeball the JSON.

### Phase 4 — Telegram bot end-to-end (local)

- [ ] @BotFather → get token.
- [ ] `bot/handlers.py`: `/start`, voice handler, text handler.
- [ ] Webhook mounted under FastAPI at `/telegram/webhook/<secret>`.
- [ ] `ngrok` tunnel, register webhook locally.
- [ ] Send a real Hebrew voice message; receive the full bundle.
- [ ] Verify entry in local Postgres.

### Phase 5 — Google Drive storage

- [ ] Service account + folder set up (runbook §9.2).
- [ ] `drive.py` `save_transcript`, `save_entry_json`.
- [ ] Pipeline writes to Drive after Postgres.
- [ ] Verify files appear.

### Phase 6 — Commands beyond `/start`

- [ ] `/last`, `/show <id>`, `/questions`, `/search <text>`.
- [ ] `/edit <id>` flow (state stored in `entries.status='editing'` + `tg_chat_id`).
- [ ] `/restructure <id>`.
- [ ] `/tags <id>` overwrite flow.
- [ ] `/usage` aggregate.

### Phase 7 — Background reliability

- [ ] `lifespan` task: retry `needs_structuring` every 30 min.
- [ ] `lifespan` task: daily digest at 09:00.
- [ ] Idempotency cache on `update_id`.
- [ ] Test: kill process mid-pipeline, ensure recovery.

### Phase 8 — Railway deploy

- [ ] Push to GitHub.
- [ ] Connect repo to Railway. Add Postgres add-on. Add volume.
- [ ] Set env vars per §11.
- [ ] First deploy succeeds, `alembic upgrade head` runs.
- [ ] Run `scripts/set_webhook.sh` with prod `BASE_URL`.
- [ ] Send a real voice message from phone. Receive reply. Check Drive.

### Phase 9 — Hardening

- [ ] Add structlog with request IDs.
- [ ] Tighten rate limits / catch obviously hostile inputs.
- [ ] Document runbook in `README.md`.

MVP = Phases 0–5 + the parts of Phase 6 needed for `/edit`.

---

## 18. Future Vision (post-MVP)

* Embeddings on `entries.transcript` for semantic search (`pgvector`).
* Normalized `entities` table — people, places, events with aliases.
* Chapter generation: cluster entries by tag + timeline + entities, ask LLM to draft.
* Weekly summary DM: "this week you added 3 entries about family, here are themes".
* Family-mode multi-user: per-user Drive folder, `entries.user_id`.
* Voice replies: bot reads its summary aloud (TTS).
* Soft re-transcription: keep audio for 1 h in memory only, allow `/retry` once.

---

## Final Principle

Treat each memory as a **structured data point**, not just text.
Audio is ephemeral; transcript and structure are forever.
Everything later — search, chapters, the full biography — depends on this discipline.
