# HMND AI Governance Dashboard

Streamlit-дашборд для мониторинга расходов на OpenAI и Anthropic, утилизации сидений, активности разработчиков и доли AI-кода в репозиториях.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Создать БД и засеять демо-данные (генерирует ~30 дней usage_events, PR'ы, alerts)
python -m scripts.init_db

# 2. Запустить дашборд
streamlit run frontend/app.py
```

После старта дашборд доступен на http://localhost:8501.

## Структура

```
docs/SPEC.md         — Спецификация: Feature → US → BDD → FR/NFR → Tests
data/                — Слой данных (schema, models, seed, коннекторы)
backend/             — Слой сервисов (KPI, costs, seats, alerts, ...)
frontend/            — Streamlit UI (theme + pages)
tests/               — Тесты по ID требований из спеки
scripts/             — init_db, sync, ad-hoc задачи
```

## Подключение реальных источников

В `Settings` в дашборде вводятся ключи:

- `OPENAI_API_KEY` — Usage API.
- `ANTHROPIC_API_KEY` — Usage API.
- `GITHUB_TOKEN` — для PR/commit метаданных.

Без ключей дашборд работает в `mock=True` режиме на seed-данных.

## Тесты

```bash
pytest -q
```

Каждый тест подписан ID требования из `docs/SPEC.md`.
