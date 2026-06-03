#!/usr/bin/env bash
# Helper to document / scaffold a new customer Render Background Worker.
# Usage: ./scripts/new-customer.sh customer-slug "Display Name"
#
# Requires Render CLI (https://render.com/docs/cli) for automated create.
# Without the CLI, the script prints manual dashboard steps.

set -euo pipefail

SLUG="${1:-}"
DISPLAY_NAME="${2:-$SLUG}"
REPO="${RENDER_REPO:-https://github.com/okwujiaku/scraper}"
ROOT_DIR="bot"

if [[ -z "$SLUG" ]]; then
  echo "Usage: ./scripts/new-customer.sh <customer-slug> [Display Name]"
  echo "Example: ./scripts/new-customer.sh stevo Stevo"
  exit 1
fi

SERVICE_NAME="scraper-${SLUG}"

echo "=== New customer: ${DISPLAY_NAME} (${SERVICE_NAME}) ==="
echo ""
echo "Render Background Worker settings:"
echo "  Name:          ${SERVICE_NAME}"
echo "  Root Directory: ${ROOT_DIR}"
echo "  Build Command: pip install -r requirements.txt"
echo "  Start Command: python bot.py"
echo "  Repo:          ${REPO}"
echo ""
echo "Environment variables to set:"
echo "  TOKEN=       (customer Discord user token)"
echo "  CHAT_ID=     (customer group chat ID)"
echo "  CLIENT_NAME= ${DISPLAY_NAME}"
echo "  PYTHON_VERSION=3.11.9"
echo ""

if command -v render >/dev/null 2>&1; then
  echo "Render CLI detected. Create the service in the dashboard, then:"
  echo "  render env set TOKEN --service ${SERVICE_NAME}"
  echo "  render env set CHAT_ID --service ${SERVICE_NAME}"
  echo "  render env set CLIENT_NAME='${DISPLAY_NAME}' --service ${SERVICE_NAME}"
else
  echo "Manual steps (Render Dashboard):"
  echo "  1. New + → Background Worker"
  echo "  2. Connect repo: ${REPO}"
  echo "  3. Root Directory: ${ROOT_DIR}"
  echo "  4. Build: pip install -r requirements.txt"
  echo "  5. Start: python bot.py"
  echo "  6. Add env vars above → Deploy"
fi

echo ""
echo "Customer must join their Discord servers with THIS account (not a shared account)."
