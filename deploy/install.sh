#!/usr/bin/env bash
# Bootstrap HMND dashboard на чистой Ubuntu 22.04.
# Использование (на VM):
#   bash deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"

echo "[1/6] apt deps…"
sudo apt update -y
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx apache2-utils

echo "[2/6] virtualenv + requirements…"
cd "$APP_DIR"
python3.11 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[3/6] .env (если ещё нет)…"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "  -> отредактируй $APP_DIR/.env (OPENAI_API_KEY, ANTHROPIC_API_KEY) и снова запусти."
fi

echo "[4/6] schema init…"
"$APP_DIR/.venv/bin/python" -m scripts.init_db || true

echo "[5/6] systemd units…"
sudo sed -e "s|__USER__|$USER_NAME|g" -e "s|__APP_DIR__|$APP_DIR|g" \
  "$APP_DIR/deploy/hmnd-dashboard.service" | sudo tee /etc/systemd/system/hmnd-dashboard.service >/dev/null
sudo sed -e "s|__USER__|$USER_NAME|g" -e "s|__APP_DIR__|$APP_DIR|g" \
  "$APP_DIR/deploy/hmnd-sync.service" | sudo tee /etc/systemd/system/hmnd-sync.service >/dev/null
sudo cp "$APP_DIR/deploy/hmnd-sync.timer" /etc/systemd/system/hmnd-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now hmnd-dashboard
sudo systemctl enable --now hmnd-sync.timer

echo "[6/6] nginx + basic auth…"
if [[ ! -f /etc/nginx/.htpasswd ]]; then
  echo "  -> создай пароль: sudo htpasswd -c /etc/nginx/.htpasswd andrey"
fi
sudo tee /etc/nginx/sites-available/hmnd >/dev/null <<'EOF'
server {
    listen 80 default_server;
    server_name _;

    auth_basic "HMND Dashboard";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/hmnd /etc/nginx/sites-enabled/hmnd
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo
echo "Готово."
echo "  → systemctl status hmnd-dashboard"
echo "  → journalctl -u hmnd-dashboard -f"
echo "  → открой http://<EXTERNAL_IP>"
