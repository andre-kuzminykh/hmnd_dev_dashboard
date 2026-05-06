#!/usr/bin/env bash
# Expose HMND AIOps Dashboard on the public internet via:
#   nginx (reverse proxy) + Let's Encrypt (TLS)
#   Optionally guarded by basic auth.
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
#   bash deploy/expose-public.sh <username> <email-for-lets-encrypt>           # with basic auth
#   bash deploy/expose-public.sh _ <email-for-lets-encrypt> --no-auth          # public, no auth
#
# Examples:
#   bash deploy/expose-public.sh andrey andrey@hmnd.ai
#   bash deploy/expose-public.sh _ andrey@hmnd.ai --no-auth
set -euo pipefail

USER_NAME="${1:-}"
LE_EMAIL="${2:-}"
MODE="${3:-with-auth}"   # --no-auth flips this off
if [[ "${MODE}" == "--no-auth" ]]; then
  AUTH=0
else
  AUTH=1
fi

if [[ -z "$LE_EMAIL" ]]; then
  echo "usage:"
  echo "  $0 <username> <email-for-lets-encrypt>            # with basic auth"
  echo "  $0 _ <email-for-lets-encrypt> --no-auth           # no auth (public)"
  exit 1
fi

# 1) Detect external IP (GCE metadata service, works on every GCP VM)
EXTERNAL_IP=$(curl -fsSL -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || true)

if [[ -z "${EXTERNAL_IP}" ]]; then
  EXTERNAL_IP=$(curl -fsSL https://api.ipify.org || true)
fi
if [[ -z "${EXTERNAL_IP}" ]]; then
  echo "[!] could not detect external IP"
  exit 1
fi

# DNS hostname. By default uses sslip.io but you can override via env, e.g.:
#   HMND_PUBLIC_DOMAIN=hmnd.34.62.139.101.nip.io bash deploy/expose-public.sh ...
# nip.io is the usual fallback when sslip.io hits Let's Encrypt's per-domain
# weekly cert quota.
if [[ -n "${HMND_PUBLIC_DOMAIN:-}" ]]; then
  DOMAIN="${HMND_PUBLIC_DOMAIN}"
else
  DOMAIN_BASE="${HMND_DOMAIN_BASE:-sslip.io}"
  if [[ "${DOMAIN_BASE}" == "nip.io" ]]; then
    DOMAIN="hmnd.${EXTERNAL_IP}.${DOMAIN_BASE}"
  else
    DOMAIN="hmnd-${EXTERNAL_IP//./-}.${DOMAIN_BASE}"
  fi
fi
echo "[+] Public URL will be https://${DOMAIN}"
echo "[+] External IP:        ${EXTERNAL_IP}"
echo "[+] Mode:               $([[ $AUTH -eq 1 ]] && echo "basic auth (user: ${USER_NAME})" || echo "no auth (public)")"
echo

# 2) Install dependencies
sudo apt update -y
sudo apt install -y nginx certbot python3-certbot-nginx apache2-utils

# 3) Basic auth (optional)
if [[ $AUTH -eq 1 ]]; then
  if [[ -z "${USER_NAME}" || "${USER_NAME}" == "_" ]]; then
    echo "[!] basic auth mode requires a real username (not '_')"
    exit 1
  fi
  if [[ ! -f /etc/nginx/.htpasswd ]]; then
    echo "[+] Setting password for user '${USER_NAME}' (this is the password your team will type)"
    sudo htpasswd -c /etc/nginx/.htpasswd "$USER_NAME"
  else
    echo "[i] /etc/nginx/.htpasswd already exists — keeping it; add more users with"
    echo "    sudo htpasswd /etc/nginx/.htpasswd <name>"
  fi
else
  # In no-auth mode make sure no stale htpasswd is present
  sudo rm -f /etc/nginx/.htpasswd
fi

# 4) nginx site
if [[ $AUTH -eq 1 ]]; then
  AUTH_BLOCK=$'    auth_basic "HMND AIOps Dashboard";\n    auth_basic_user_file /etc/nginx/.htpasswd;\n'
  ACME_OVERRIDE=$'    location ^~ /.well-known/acme-challenge/ {\n        auth_basic off;\n        root /var/www/html;\n    }\n'
else
  AUTH_BLOCK=""
  ACME_OVERRIDE=$'    location ^~ /.well-known/acme-challenge/ {\n        root /var/www/html;\n    }\n'
fi

sudo tee /etc/nginx/sites-available/hmnd >/dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

${AUTH_BLOCK}    location / {
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

${ACME_OVERRIDE}}
EOF

sudo ln -sf /etc/nginx/sites-available/hmnd /etc/nginx/sites-enabled/hmnd
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# 5) TLS via Let's Encrypt
echo "[+] Requesting Let's Encrypt certificate for ${DOMAIN}…"
sudo certbot --nginx -d "${DOMAIN}" \
  --email "${LE_EMAIL}" --agree-tos --redirect --non-interactive

# 6) Done
cat <<DONE

[✓] Dashboard is live at:
    https://${DOMAIN}

DONE

if [[ $AUTH -eq 1 ]]; then
  echo "User: ${USER_NAME}"
  echo "(the password you set above)"
  echo
  echo "Add more users:"
  echo "    sudo htpasswd /etc/nginx/.htpasswd <name>"
else
  echo "Mode: public — no login required."
  echo "If you change your mind:"
  echo "    sudo htpasswd -c /etc/nginx/.htpasswd andrey"
  echo "    add inside the server { } block:"
  echo "        auth_basic \"HMND AIOps Dashboard\";"
  echo "        auth_basic_user_file /etc/nginx/.htpasswd;"
  echo "    sudo nginx -t && sudo systemctl reload nginx"
fi

echo
echo "To rotate cert (auto-renewed by certbot.timer, but to test):"
echo "    sudo certbot renew --dry-run"
echo
echo "Logs:"
echo "    sudo journalctl -u nginx -f"
echo "    docker compose logs -f dashboard"
