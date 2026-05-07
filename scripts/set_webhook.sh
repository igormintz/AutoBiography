#!/usr/bin/env bash
# Register the Telegram webhook with Telegram's Bot API.
# Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, BASE_URL from .env.
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . .env
  set +a
fi

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN missing}"
: "${TELEGRAM_WEBHOOK_SECRET:?TELEGRAM_WEBHOOK_SECRET missing}"
: "${BASE_URL:?BASE_URL missing}"

URL="${BASE_URL%/}/telegram/webhook/${TELEGRAM_WEBHOOK_SECRET}"
echo "Setting webhook to: $URL"

curl -fsSL -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${URL}" \
  --data-urlencode 'allowed_updates=["message"]'

echo
