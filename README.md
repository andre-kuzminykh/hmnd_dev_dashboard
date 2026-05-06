# HMND AI Governance Dashboard

Streamlit-дашборд для мониторинга расходов на OpenAI и Anthropic, утилизации сидений, активности разработчиков и доли AI-кода в репозиториях.

## Локальный запуск (для проверки)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # заполнить ключи
export $(grep -v '^#' .env | xargs)  # подгрузить env-переменные

# Создать схему БД
python -m scripts.init_db

# (Опционально) подтянуть реальные данные за 7 дней
python -m scripts.sync --days 7

# Запустить
streamlit run frontend/app.py --server.port 7501
```

Откроется на http://localhost:7501.

## Переменные окружения

| Переменная | Описание |
|---|---|
| `OPENAI_API_KEY` | OpenAI Organization Admin key (`sk-admin-...`) |
| `ANTHROPIC_API_KEY` | Anthropic Admin key (для `/v1/organizations/...`) |
| `GITHUB_TOKEN` | GitHub PAT (только если `HMND_GITHUB_ENABLED=true`) |
| `HMND_GITHUB_ENABLED` | `true/false` — показывать страницы Repositories/PR Quality и AI code share KPI |
| `HMND_DEMO_DATA` | `true` — засеять демо-данные (для разработки) |
| `HMND_DB_PATH` | путь к SQLite (по умолчанию `./data/hmnd.db`) |

## Деплой

Полные шаги — в [`docs/DEPLOY.md`](docs/DEPLOY.md). Кратко два варианта:

### Docker (рекомендуется, изолированно от хоста)

```bash
git clone <repo> hmnd_dev_dashboard && cd hmnd_dev_dashboard
git checkout claude/token-monitoring-dashboard-aDaNV
cp .env.example .env && nano .env       # OPENAI_API_KEY, ANTHROPIC_API_KEY
chmod 600 .env
docker compose up -d --build
```

UI слушает `127.0.0.1:7501` — поставь свой reverse-proxy перед ним.
Sync крутится в сайдкаре `hmnd-sync` каждый час.

### systemd на хост

```bash
git clone <repo> hmnd_dev_dashboard && cd hmnd_dev_dashboard
bash deploy/install.sh
nano .env && sudo systemctl restart hmnd-dashboard
sudo htpasswd -c /etc/nginx/.htpasswd andrey
```

## Структура

```
docs/SPEC.md         — Спецификация: Feature → US → BDD → FR/NFR → Tests
docs/DEPLOY.md       — Пошаговый деплой
data/                — Слой данных (schema, models, seed, коннекторы)
backend/             — Слой сервисов (KPI, costs, seats, alerts, sync, …)
frontend/            — Streamlit UI (theme + pages)
tests/               — Тесты по ID требований
scripts/init_db.py   — создать/пересоздать схему
scripts/sync.py      — pull данных из OpenAI/Anthropic/GitHub
deploy/              — systemd units + install.sh
```

## Тесты

```bash
pytest -q
```
