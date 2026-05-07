"""Pre-download the Whisper model into HF_HOME at image build time.

The runtime never has to fetch weights — `WhisperModel(...)` finds the
snapshot already populated under `<HF_HOME>/models--<owner>--<name>/`.

Run during `docker build`:

    uv run python scripts/download_model.py

Honors `WHISPER_MODEL` (defaults to `ivrit-ai/whisper-large-v3-turbo-ct2`)
and `HF_HOME` (defaults to `/data/hf-cache`).
"""

from __future__ import annotations

import os

DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"
DEFAULT_HF_HOME = "/data/hf-cache"


def main() -> None:
    from huggingface_hub import snapshot_download

    repo_id = os.environ.get("WHISPER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    cache_dir = os.environ.get("HF_HOME", DEFAULT_HF_HOME).strip() or DEFAULT_HF_HOME

    os.makedirs(cache_dir, exist_ok=True)
    print(f"[download_model] fetching {repo_id} into {cache_dir}", flush=True)
    path = snapshot_download(repo_id=repo_id, cache_dir=cache_dir)
    print(f"[download_model] snapshot ready at {path}", flush=True)


if __name__ == "__main__":
    main()
