"""Vercel Python serverless entrypoint.

Vercel auto-detects the ASGI `app` exported here and serves it through its
Python runtime. Routing is configured in `vercel.json` (all paths are
rewritten to this function), so `/healthz`, `/telegram/webhook/<secret>`,
`/api/cron/*`, etc. are handled by the FastAPI app defined in `app.main`.
"""

from __future__ import annotations

from app.main import app

__all__ = ["app"]
