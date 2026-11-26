#!/usr/bin/env bash
# Demo-day launcher: shared backend (:8000) + owner dashboard (:8001, LAN-visible).
# Credentials come from backend_login.json (gitignored) — never from this file.
# Data lives in repo/jamrock_data (gitignored) so it survives /tmp cleanup.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASH="$ROOT/owner-dashboard"
VENV="$DASH/venv"
DATA="$ROOT/jamrock_data"
LOGIN="$DASH/backend_login.json"

if [ ! -f "$LOGIN" ]; then
  echo "Missing $LOGIN — create {\"username\": \"...\", \"password\": \"...\"} with the Owner login."
  exit 1
fi

cd "$ROOT"

# Ensure Owner/Cashier/Kitchen users exist (idempotent; password from the login file).
JAMROCK_DATA_DIR="$DATA" "$VENV/bin/python" - "$LOGIN" <<'PY'
import json, sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root))
from backend.database import contextmanager_connection, initialize
from backend.security import hash_password

cfg = json.loads(Path(sys.argv[1]).read_text())
db = initialize(str(root / "jamrock_data"))
with contextmanager_connection(db) as conn:
    for username, role, name in [
        ("owner", "Owner", "Jevoy Johnson"),
        ("cashier", "Cashier", "Cash Desk"),
        ("kitchen", "Kitchen", "Kitchen Line"),
    ]:
        if not conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            conn.execute(
                "INSERT INTO users(username,display_name,role,password_hash) VALUES (?,?,?,?)",
                (username, name, role, hash_password(cfg["password"])),
            )
print("users ready")
PY

# Shared backend — localhost only; the dashboard proxies to it.
if ! curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  setsid -f env JAMROCK_DATA_DIR="$DATA" "$VENV/bin/uvicorn" backend.main:app \
    --port 8000 --host 127.0.0.1 > /tmp/jamrock-backend.log 2>&1
  sleep 3
fi

# Owner dashboard — 0.0.0.0 so a phone on the same Wi-Fi (or Tailscale) can open it.
if ! curl -sf --max-time 2 http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
  setsid -f "$VENV/bin/uvicorn" main:app --app-dir "$DASH" \
    --port 8001 --host 0.0.0.0 > /tmp/jamrock-dashboard.log 2>&1
  sleep 3
fi

IP_LAN=$(hostname -I 2>/dev/null | awk '{print $1}')
IP_TS=$(tailscale ip -4 2>/dev/null || true)

echo "Backend    http://127.0.0.1:8000   (POS: /pos/)"
echo "Dashboard  http://127.0.0.1:8001"
echo "Phone LAN  http://$IP_LAN:8001"
[ -n "$IP_TS" ] && echo "Tailscale  http://$IP_TS:8001"
curl -sf --max-time 4 http://127.0.0.1:8001/api/overview | "$VENV/bin/python" -c "import json,sys; d=json.load(sys.stdin); print('mode:', d['mode'], '| revenue J\$', d['revenue'], '| orders', d['orders'])" || echo "mode: (dashboard starting)"
