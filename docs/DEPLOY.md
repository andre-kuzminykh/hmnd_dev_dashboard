# Пошаговый деплой на `human-1` (GCE, Ubuntu 22.04)

> Дано: VM `human-1` в `i-crossbar-433120-v3` / `europe-west1-b`, ты уже подключился через `gcloud compute ssh`.

## Шаг 0 (✋ обязательно) — отозвать утёкшие ключи

Если ты раньше делился ключами в чате — открой и удали их **прямо сейчас**, потом сгенерируй новые:

- OpenAI: https://platform.openai.com/settings/organization/admin-keys → Delete → Create new admin key (`Read usage`, `Read costs` минимум).
- Anthropic: https://console.anthropic.com → API Keys → Revoke → создать заново. Для дашборда нужен **Admin** ключ (Settings → Admin Keys), обычный `sk-ant-api03-…` не даёт доступ к usage report.

Скопируй новые ключи в надёжное место (1Password, GCP Secret Manager). На сервер их положишь в `.env` ниже — не вставляй в чат.

---

## Шаг 1 — поставить базовый софт

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx apache2-utils
```

## Шаг 2 — клонировать проект

```bash
cd ~
git clone https://github.com/andre-kuzminykh/hmnd_dev_dashboard.git
cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV   # пока ветка не смержена
```

## Шаг 3 — автоустановка через скрипт

```bash
bash deploy/install.sh
```

Что он делает:
1. Создаёт `.venv` и ставит зависимости.
2. Создаёт `.env` из шаблона.
3. Инициализирует пустую SQLite-схему.
4. Кладёт два systemd-юнита: `hmnd-dashboard.service` (UI) и `hmnd-sync.timer` (ежечасный sync).
5. Настраивает nginx-reverse-proxy с basic-auth.

## Шаг 4 — вписать ключи в `.env`

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

## Шаг 5 — поставить пароль на nginx

```bash
sudo htpasswd -c /etc/nginx/.htpasswd andrey
# впиши пароль дважды
```

## Шаг 6 — открыть порт 80 в GCP firewall

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

## Шаг 7 — проверить

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

## Шаг 8 — первый sync

В дашборде: **Settings → Run sync now**, либо CLI:

```bash
cd ~/hmnd_dev_dashboard
.venv/bin/python -m scripts.sync --days 30
```

После этого ходи по страницам — Overview, Costs by People, Seats, Models, Developer Usage, Alerts.

Страницы **Repositories** и **PR Quality** показывают «coming soon», пока `HMND_GITHUB_ENABLED=false`.

## Шаг 9 — HTTPS (рекомендую)

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
