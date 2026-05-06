# Пошаговый деплой на `human-1` (GCE, Ubuntu 22.04)

> Дано: VM `human-1` в `i-crossbar-433120-v3` / `europe-west1-b`, ты уже подключился через `gcloud compute ssh`.

Есть два варианта:

- **Вариант A (Docker)** — изолированный, ничего не ставит на хост кроме Docker. Рекомендуется, если на VM уже что-то крутится.
- **Вариант B (systemd на хост)** — родной вариант, без Docker.

---

## Вариант A · Docker (рекомендуется)

### A0. Отозвать утёкшие ключи (если они светились в чате)

- OpenAI: https://platform.openai.com/settings/organization/admin-keys
- Anthropic: https://console.anthropic.com → Settings → Organization → API Keys

Сгенерируй заново. Ключи кладём прямо на VM в `.env`, не в чат.

### A1. Поставить Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# выйди из ssh и зайди заново — иначе docker будет требовать sudo
exit
```

Снова подключись: `gcloud compute ssh human-1 ...`.

### A2. Клонировать проект

```bash
cd ~
git clone https://github.com/andre-kuzminykh/hmnd_dev_dashboard.git
cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV
```

### A3. Создать `.env`

```bash
cp .env.example .env
nano .env
```

Заполни `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Сохрани (`Ctrl+O`, `Enter`, `Ctrl+X`):
```bash
chmod 600 .env
```

### A4. Запустить compose

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f dashboard      # глянуть, что стартанул; Ctrl+C для выхода
```

`docker compose ps` должен показать **healthy** через 30–60 секунд. Дашборд внутри контейнера слушает 8501, наружу пробрасывается только на `127.0.0.1:8501` (на VM).

### A5. Прокинуть наружу

Два пути:

**A5.1 Свой существующий nginx/Caddy.** Просто проксируй на `127.0.0.1:8501`. Готовый snippet:
```nginx
location / {
    proxy_pass http://127.0.0.1:8501/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
}
```

**A5.2 Поднять рядом nginx и опубликовать `IP:80`** (если на хосте ничего нет):
```bash
sudo apt update && sudo apt install -y nginx apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd andrey   # пароль для входа
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
```

И открой 80 порт в GCP firewall (с локальной машины):
```bash
gcloud compute firewall-rules create allow-hmnd-http \
  --project=i-crossbar-433120-v3 --direction=INGRESS --action=ALLOW \
  --rules=tcp:80 --target-tags=http-server --source-ranges=0.0.0.0/0
gcloud compute instances add-tags human-1 \
  --tags=http-server --zone=europe-west1-b --project=i-crossbar-433120-v3
```

### A6. Первый sync

Сайдкар `hmnd-sync` делает sync каждый час. Прогнать руками:
```bash
docker compose exec sync python -m scripts.sync --days 30
# или
docker compose run --rm sync python -m scripts.sync --days 30
```

### A7. Полезные команды Docker

```bash
docker compose ps                        # статус
docker compose logs -f dashboard         # логи UI
docker compose logs -f sync              # логи sync
docker compose restart dashboard
docker compose down                      # остановить всё (без удаления данных)
docker compose down -v                   # + удалить named volumes (если будут)
docker compose pull && docker compose up -d --build   # обновить
```

Данные SQLite живут в `./data/hmnd.db` на хосте — бекапь/архивируй обычным `cp` или `tar`.

### A8. (опц.) Бекап БД

```bash
mkdir -p ~/backups
sqlite3 ~/hmnd_dev_dashboard/data/hmnd.db ".backup '/home/$USER/backups/hmnd-$(date +%F).db'"
```

---

## Вариант B · systemd на хост (без Docker)

### B0. Отозвать утёкшие ключи (см. A0)

### B1 — поставить базовый софт

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx apache2-utils
```

### B2 — клонировать проект

```bash
cd ~
git clone https://github.com/andre-kuzminykh/hmnd_dev_dashboard.git
cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV   # пока ветка не смержена
```

### B3 — автоустановка через скрипт

```bash
bash deploy/install.sh
```

Что он делает:
1. Создаёт `.venv` и ставит зависимости.
2. Создаёт `.env` из шаблона.
3. Инициализирует пустую SQLite-схему.
4. Кладёт два systemd-юнита: `hmnd-dashboard.service` (UI) и `hmnd-sync.timer` (ежечасный sync).
5. Настраивает nginx-reverse-proxy с basic-auth.

### B4 — вписать ключи в `.env`

```bash
nano ~/hmnd_dev_dashboard/.env
```

Заполни три поля:
```
OPENAI_API_KEY=sk-admin-…
ANTHROPIC_API_KEY=sk-ant-admin01-…   # пустое если admin-ключа пока нет
GITHUB_TOKEN=
HMND_GITHUB_ENABLED=false
HMND_DEMO_DATA=false
```

Сохрани (`Ctrl+O`, `Enter`, `Ctrl+X`), затем:

```bash
chmod 600 ~/hmnd_dev_dashboard/.env
sudo systemctl restart hmnd-dashboard
```

### B5 — поставить пароль на nginx

```bash
sudo htpasswd -c /etc/nginx/.htpasswd andrey
# впиши пароль дважды
```

### B6 — открыть порт 80 в GCP firewall

С локальной машины (не с VM):

```bash
gcloud compute firewall-rules create allow-hmnd-http \
  --project=i-crossbar-433120-v3 \
  --direction=INGRESS --action=ALLOW \
  --rules=tcp:80 --target-tags=http-server \
  --source-ranges=0.0.0.0/0

gcloud compute instances add-tags human-1 \
  --tags=http-server \
  --zone=europe-west1-b --project=i-crossbar-433120-v3
```

> Если хочешь сузить доступ — замени `0.0.0.0/0` на свой IP/24.

### B7 — проверить

```bash
sudo systemctl status hmnd-dashboard --no-pager
sudo systemctl status hmnd-sync.timer --no-pager
journalctl -u hmnd-dashboard -n 50 --no-pager
```

Внешний IP машины:

```bash
gcloud compute instances describe human-1 \
  --zone=europe-west1-b --project=i-crossbar-433120-v3 \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

Открой `http://<EXTERNAL_IP>` → введи логин/пароль из шага 5 → ты внутри.

### B8 — первый sync

В дашборде: **Settings → Run sync now**, либо CLI:

```bash
cd ~/hmnd_dev_dashboard
.venv/bin/python -m scripts.sync --days 30
```

После этого ходи по страницам — Overview, Costs by People, Seats, Models, Developer Usage, Alerts.

Страницы **Repositories** и **PR Quality** показывают «coming soon», пока `HMND_GITHUB_ENABLED=false`.

### B9 — HTTPS (рекомендую)

Если есть домен `dashboard.hmnd.ai` (DNS A → external IP машины):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dashboard.hmnd.ai
```

Certbot сам обновит nginx-конфиг, добавит TLS-сертификат и cron-renew.

## Регулярные операции

| Что | Как |
|---|---|
| Посмотреть логи | `journalctl -u hmnd-dashboard -f` |
| Перезапустить UI | `sudo systemctl restart hmnd-dashboard` |
| Запустить sync вручную | `.venv/bin/python -m scripts.sync --days 7` |
| Посмотреть таймер | `systemctl list-timers --all \| grep hmnd` |
| Откатить демо-данные | `HMND_DEMO_DATA=false` в `.env` + Wipe в Settings |
| Включить GitHub | поставить `HMND_GITHUB_ENABLED=true`, `GITHUB_TOKEN=…` и рестарт |

## Если что-то сломалось

- 502 на `http://<IP>/` → дашборд не запустился, смотри `journalctl -u hmnd-dashboard -n 100`.
- "permission denied" на `.env` → `sudo chown $USER:$USER .env && chmod 600 .env`.
- "Anthropic admin key required" в Settings → у тебя обычный ключ, не админский. Создать админский в Anthropic Console.
- `connect: connection refused` на 8501 при curl с VM → systemd unit не стартанул, проверь `systemctl status hmnd-dashboard`.
