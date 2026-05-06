#!/usr/bin/env bash
# Expose HMND AIOps Dashboard on the public internet via:
#   nginx (reverse proxy) + Let's Encrypt (TLS) + basic auth (shared password)
#
# Uses sslip.io for a zero-config TLS-friendly hostname tied to the VM's
# external IP — no DNS provider account needed.
#
# Prereqs (run from your laptop, NOT on the VM):
#   gcloud compute firewall-rules create allow-hmnd-web \
#     --project=<PROJECT> --direction=INGRESS --action=ALLOW \
#     --rules=tcp:80,tcp:443 --target-tags=http-server \
#     --source-ranges=0.0.0.0/0
#   gcloud compute instances add-tags <VM_NAME> --tags=http-server \
#     --zone=<ZONE> --project=<PROJECT>
#
# Usage on the VM:
#   bash deploy/expose-public.sh <username> <email-for-lets-encrypt>
# Example:
#   bash deploy/expose-public.sh andrey andrey@hmnd.ai
#
# After the script finishes you will get a URL like
#   https://hmnd-<external-ip-with-dashes>.sslip.io
# and a basic-auth login (the password you set during the run).
set -euo pipefail

USER_NAME="${1:-}"
LE_EMAIL="${2:-}"
if [[ -z "$USER_NAME" || -z "$LE_EMAIL" ]]; then
  echo "usage: $0 <username> <email-for-lets-encrypt>"
  exit 1
fi

# 1) Detect external IP (GCE metadata service, works on every GCP VM)
EXTERNAL_IP=$(curl -fsSL -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || true)

if [[ -z "${EXTERNAL_IP}" ]]; then
  # Fallback for non-GCE hosts
  EXTERNAL_IP=$(curl -fsSL https://api.ipify.org || true)
fi

if [[ -z "${EXTERNAL_IP}" ]]; then
  echo "[!] could not detect external IP"
  exit 1
fi

DOMAIN="hmnd-${EXTERNAL_IP//./-}.sslip.io"
echo "[+] Public URL will be https://${DOMAIN}"
echo "[+] External IP:        ${EXTERNAL_IP}"
echo

# 2) Install dependencies
sudo apt update -y
sudo apt install -y nginx certbot python3-certbot-nginx apache2-utils

# 3) Basic auth (one shared password for the team)
if [[ ! -f /etc/nginx/.htpasswd ]]; then
  echo "[+] Setting password for user '${USER_NAME}' (this is the password your team will type)"
  sudo htpasswd -c /etc/nginx/.htpasswd "$USER_NAME"
else
  echo "[i] /etc/nginx/.htpasswd already exists — keeping it; add more users with"
  echo "    sudo htpasswd /etc/nginx/.htpasswd <name>"
fi

# 4) nginx site (HTTP first; certbot will add HTTPS + redirect)
sudo tee /etc/nginx/sites-available/hmnd >/dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    auth_basic "HMND AIOps Dashboard";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:7501/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    # Allow Let's Encrypt HTTP-01 challenge without basic auth
    location ^~ /.well-known/acme-challenge/ {
        auth_basic off;
        root /var/www/html;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/hmnd /etc/nginx/sites-enabled/hmnd
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# 5) TLS via Let's Encrypt (certbot will edit the nginx site to add 443 + redirect)
echo "[+] Requesting Let's Encrypt certificate for ${DOMAIN}…"
sudo certbot --nginx -d "${DOMAIN}" \
  --email "${LE_EMAIL}" --agree-tos --redirect --non-interactive

# 6) Done
cat <<DONE

[✓] Dashboard is live at:
    https://${DOMAIN}

User: ${USER_NAME}
(the password you set above)

To add more users:
    sudo htpasswd /etc/nginx/.htpasswd <name>

To rotate cert (auto-renewed by certbot.timer, but to test):
    sudo certbot renew --dry-run

Logs:
    sudo journalctl -u nginx -f
    docker compose logs -f dashboard
DONE
