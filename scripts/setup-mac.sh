#!/usr/bin/env bash
# One-shot local setup for macOS. Idempotent — safe to re-run.
#   bash scripts/setup-mac.sh
# Installs: Homebrew (if missing), Python 3.12, Node 22, Postgres 16; creates the venv, DB, console build.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if ! command -v brew >/dev/null; then
  say "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

say "Installing python@3.12, node@22, postgresql@16"
brew install python@3.12 node@22 postgresql@16 >/dev/null
brew link --overwrite --force node@22 >/dev/null 2>&1 || true
PG_BIN="$(brew --prefix postgresql@16)/bin"
export PATH="$PG_BIN:$PATH"

say "Starting Postgres and creating the ledgerline database"
brew services start postgresql@16 >/dev/null
for i in $(seq 1 20); do "$PG_BIN/pg_isready" -q && break; sleep 1; done
"$PG_BIN/psql" -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='ledgerline'" | grep -q 1 \
  || "$PG_BIN/psql" -d postgres -c "CREATE USER ledgerline WITH PASSWORD 'ledgerline' SUPERUSER;"
"$PG_BIN/psql" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='ledgerline'" | grep -q 1 \
  || "$PG_BIN/psql" -d postgres -c "CREATE DATABASE ledgerline OWNER ledgerline;"

say "Python environment"
PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e "backend[dev]"

say "PayPal MCP server (node) and console build"
(cd backend && npm ci --silent)
(cd frontend && npm ci --silent && npm run build --silent)

say "Database migrations"
[ -f backend/.env ] || cp backend/.env.example backend/.env
(cd backend && ledgerline migrate)

say "Done. Next:"
cat <<'EOF'
  1. Put PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET in backend/.env
  2. source .venv/bin/activate && cd backend
  3. ledgerline sim seed && ledgerline sim inject && ledgerline drain
  4. ledgerline api   -> http://localhost:8000
EOF
