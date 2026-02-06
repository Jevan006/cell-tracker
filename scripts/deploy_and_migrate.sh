#!/usr/bin/env bash
set -euo pipefail

# Deploy + migrate helper (Git Bash friendly)
# Fill in your DATABASE_URL and restart command before use.

    export FLASK_APP=app.py

    if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "DATABASE_URL is not set. Set it in your environment before running this script."
    exit 1
    fi
    if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
    echo "ADMIN_PASSWORD is not set. Set it in your environment before running this script."
    exit 1
    fi
    if [[ -z "${SESSION_SECRET:-}" ]]; then
    echo "SESSION_SECRET is not set. Set it in your environment before running this script."
    exit 1
    fi

echo "Running migrations..."
python -m flask db upgrade

echo "Restarting app..."
# TODO: Replace with your actual restart command, for example:
# systemctl restart cell-tracker
# pm2 restart cell-tracker
# render services restart <service-id>
echo "RESTART COMMAND NOT SET"

echo "Health check..."
curl -fsS http://127.0.0.1:5000/healthz || true
