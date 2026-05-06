# HMND AI Governance Dashboard — Specification

> Источник правды для разработки. Иерархия: **Feature → User Story → BDD Scenario → Requirements (FR/NFR) → Tests → Implementation by layers (Data / Backend / Frontend)**.

## Условные обозначения ID

| Префикс | Значение |
|---------|----------|
| `F-XX` | Feature |
| `US-XX.Y` | User Story (`XX` — фича, `Y` — порядковый номер) |
| `SC-XX.Y.Z` | BDD-сценарий |
| `FR-XX.Y.Z.N` | Функциональное требование |
| `NFR-XX.Y.Z.N` | Нефункциональное требование |
| `T-<ReqID>` | Тест, проверяющий конкретное требование |

Каждое требование имеет ровно один ID и хотя бы один тест с тем же ID.

---

## F-01 — Executive Overview

**Цель:** Топ-уровень для CEO/COO: одним взглядом увидеть совокупный AI-расход, вовлечённость, утилизацию сидений и долю AI-кода.

### US-01.1 — KPI-карточки сверху

> *As a* C-level executive
> *I want* видеть KPI-карточки с total spend, tokens, active users, seats used, cost per user, AI code share, suspicious activity
> *so that* за 5 секунд понимать состояние AI-операций.

#### SC-01.1.1 — Загрузка дашборда с данными за период

```gherkin
Given в БД есть usage_events за последние 30 дней по двум провайдерам
And в БД есть seats и users
When пользователь открывает страницу "Overview" с фильтром period=30d
Then над основными блоками отрисованы 7 KPI-карточек
And значения: total_spend, tokens_in, tokens_out, active_users, seats_used, cost_per_user, ai_code_share, suspicious_count
And у каждой KPI указан delta vs прошлый период с цветным бейджем (зелёный/красный)
```

**Требования сценария:**

- **FR-01.1.1.1** — Метод `get_overview_kpis(period, provider, team)` возвращает dict с 8 числовыми ключами: `total_spend`, `tokens_in`, `tokens_out`, `active_users`, `seats_used`, `cost_per_user`, `ai_code_share`, `suspicious_count`.
- **FR-01.1.1.2** — Метод считает `cost_per_user = total_spend / active_users`, при `active_users == 0` возвращает `0.0` без деления на ноль.
- **FR-01.1.1.3** — Каждая KPI содержит `delta_pct` относительно предыдущего эквивалентного периода (тот же диапазон, сдвинутый назад).
- **FR-01.1.1.4** — UI отрисовывает ровно 7 видимых KPI-карточек в шапке Overview, читая значения из FR-01.1.1.1.
- **NFR-01.1.1.1** — Расчёт KPI на 100k usage_events завершается ≤ 800 мс на SQLite.
- **NFR-01.1.1.2** — Карточки подчиняются цветовой палитре HMND (`--navy #06091c`, `--blue #4953d8`).

#### SC-01.1.2 — Фильтры пересчитывают KPI

```gherkin
Given открыта страница Overview с period=30d
When пользователь меняет provider на "anthropic"
Then KPI пересчитываются только по событиям provider="anthropic"
And total_spend не превышает значения "All" из предыдущего шага
```

**Требования:**

- **FR-01.1.2.1** — Все аналитические сервисы принимают параметр `provider ∈ {"all","openai","anthropic"}` и фильтруют по нему.
- **FR-01.1.2.2** — Фильтр team ∈ {`Backend`, `Frontend`, `Data`, `Product`, `All`} применяется через JOIN с таблицей `users.team`.
- **NFR-01.1.2.1** — Состояние фильтров кэшируется на сессию через `st.session_state["filters"]`.

---

## F-02 — Costs by People

### US-02.1 — Таблица расходов по пользователям

> *As a* Finance/Ops lead
> *I want* видеть таблицу с расходом по людям, разбитым по провайдеру, и графики поверх неё
> *so that* находить аутлаеров и считать unit-economics на разработчика.

#### SC-02.1.1 — Таблица с данными за период

```gherkin
Given выбран период 7d
When пользователь открывает "Costs by People"
Then отрисовывается таблица со столбцами: User, Team, OpenAI $, Anthropic $, Tokens in, Tokens out, Models, Last activity, Limit status
And строки отсортированы по убыванию суммы (OpenAI $ + Anthropic $)
And таблица содержит ровно по одной строке на пользователя с активностью в периоде
```

**Требования:**

- **FR-02.1.1.1** — Сервис `get_costs_by_user(period, provider, team)` возвращает список dict-ов с полями: `user_id`, `user_name`, `team`, `cost_openai`, `cost_anthropic`, `tokens_in`, `tokens_out`, `models` (list[str]), `last_activity` (datetime), `limit_status` (`ok|warn|breach`).
- **FR-02.1.1.2** — `limit_status` рассчитывается как: `ok` если `cost < 0.8 * monthly_limit`, `warn` если `0.8 ≤ cost < 1.0`, `breach` если `cost ≥ monthly_limit`.
- **FR-02.1.1.3** — Bar chart показывает сумму расходов по людям; stacked bar — OpenAI vs Anthropic.
- **FR-02.1.1.4** — Heatmap day×user показывает активность за период (значение = `tokens_in + tokens_out`).
- **NFR-02.1.1.1** — Таблица поддерживает сортировку по любому числовому столбцу (Streamlit dataframe).

#### SC-02.1.2 — Detect spend anomaly

```gherkin
Given пользователь "Ivan" имеет средний дневной расход $5 в последние 30 дней
And сегодня его расход $80
When алгоритм аномалий запускается
Then "Ivan" попадает в список suspicious_users
And под его строкой в таблице рисуется бейдж "spike"
```

**Требования:**

- **FR-02.1.2.1** — Алгоритм аномалий: пользователь помечается `spike`, если `today_cost > 3 × mean(last_30d)` И `today_cost > 20 USD`.
- **FR-02.1.2.2** — Список suspicious пишется в таблицу `alerts` с типом `spend_spike`.
- **NFR-02.1.2.1** — Алгоритм работает по pre-агрегированной view `daily_costs`, не сканирует raw `usage_events`.

---

## F-03 — Seats & Licenses

### US-03.1 — Видимость утилизации платных мест

> *As an* Ops manager
> *I want* видеть, кто из выданных сидений реально используется
> *so that* отзывать неиспользуемые места и считать экономию.

#### SC-03.1.1 — Сводка сидений

```gherkin
Given в БД 50 seats куплено, 42 назначено, 31 активен за 30d
When пользователь открывает "Seats & Licenses"
Then отображаются числа: Bought=50, Assigned=42, Active 30d=31, Inactive paid=11
And потенциальная waste = Inactive paid × средняя цена сидения
```

**Требования:**

- **FR-03.1.1.1** — Сервис `get_seats_summary()` возвращает: `bought`, `assigned`, `active_30d`, `inactive_paid`, `potential_waste_usd`.
- **FR-03.1.1.2** — `inactive_paid` = seats со статусом `assigned` И `last_used_at < now() - 30d` (или `NULL`).
- **FR-03.1.1.3** — Таблица сидений содержит: User, Seat type, Provider, Assigned (bool), Last used, Usage 30d, Recommendation (`keep|review|revoke`).
- **FR-03.1.1.4** — Recommendation: `revoke` если `last_used_at < now() - 30d`, `review` если `last_used_at в [14d, 30d]`, иначе `keep`.

---

## F-04 — Developer AI Usage

### US-04.1 — Карта использования по разработчикам

> *As an* Engineering manager
> *I want* видеть, сколько каждый разработчик тратит токенов и денег, какую долю AI-кода даёт
> *so that* понимать ROI и подсвечивать гиперактивных/недоиспользующих.

#### SC-04.1.1 — Таблица + графики

```gherkin
Given фильтр team=Backend, period=30d
When пользователь открывает "Developer Usage"
Then таблица показывает: Developer, AI requests, Tokens, Cost, Repos touched, PRs, AI code %, Review issues
And есть график "Cost vs AI code %" — точечная диаграмма для поиска корреляции
```

**Требования:**

- **FR-04.1.1.1** — Сервис `get_developer_usage(period, team)` объединяет данные из `usage_events`, `pull_requests`, `commits`, `ai_code_attribution`.
- **FR-04.1.1.2** — `ai_code_pct = sum(ai_lines) / sum(total_lines)` за период по разработчику; при `total_lines == 0` возвращает `None` и в UI рисуется тире.
- **FR-04.1.1.3** — В UI есть кликабельная ссылка с разработчика на drill-down (его модели, PR, репо).
- **NFR-04.1.1.1** — Drill-down открывается на той же странице через `st.session_state["drilldown_user"]` без full reload.

---

## F-05 — Repositories & AI Code %

### US-05.1 — Доля AI-кода в репозиториях

> *As a* CTO
> *I want* видеть, сколько % кода в каждом репозитории создано ИИ
> *so that* контролировать качество и риск критических компонентов.

#### SC-05.1.1 — Таблица репозиториев

```gherkin
Given в БД есть данные по 5 репозиториям с метками AI-attribution
When пользователь открывает "Repositories"
Then таблица показывает: Repo, Commits, PRs, Lines added, AI-attributed lines, AI code %, Risk
And Risk = "high" для критических repo с AI% > 60
```

**Требования:**

- **FR-05.1.1.1** — Сервис `get_repos_overview(period)` возвращает агрегаты по `repositories` и `commits`, `pull_requests`, `ai_code_attribution`.
- **FR-05.1.1.2** — Источники AI-attribution (в порядке доверия): `commit_message_marker` ("AI-assisted: yes"), `pr_template_flag`, `agent_metadata` (commit trailer `Co-authored-by: claude`/`copilot`/`cursor`/`codex`), `heuristic_block_size` (≥ 40 строк за один коммит).
- **FR-05.1.1.3** — Risk-классификация: `high` если репо помечен `is_critical=True` И `ai_code_pct > 60`; `medium` если `ai_code_pct > 40`; иначе `low`.
- **NFR-05.1.1.1** — Источник AI-attribution и confidence сохраняются в таблицу `ai_code_attribution` для аудита.

---

## F-06 — PR Quality

### US-06.1 — Качество AI-кода через призму PR

> *As a* Tech lead
> *I want* видеть PR'ы с долей AI-кода, ревью-комментарии, баги после мержа, флаги rollback
> *so that* находить рискованные PR и улучшать процессы ревью.

#### SC-06.1.1 — Таблица и risk score

```gherkin
Given PR #123 имеет AI%=80, 2 review comments, 1 баг после мержа, changed 3 critical files
When открывается "PR Quality"
Then в строке PR #123 risk_score рассчитан по формуле и виден бейдж "high"
```

**Требования:**

- **FR-06.1.1.1** — `risk_score = ai_code_pct/100 × (1 + critical_files_changed) × max(1, review_comments) × (1 + bug_count)` с округлением до 2 знаков.
- **FR-06.1.1.2** — Бейдж: `high` ≥ 5.0, `medium` ≥ 2.0, иначе `low`.
- **FR-06.1.1.3** — Сервис `get_pr_quality(period, repo)` возвращает PR'ы, отсортированные по `risk_score desc`.

---

## F-07 — Models

### US-07.1 — Сравнение моделей по стоимости и ошибкам

> *As an* Architect
> *I want* видеть какие модели сколько стоят и кто их основной потребитель
> *so that* находить возможности заменить модель на дешевле.

#### SC-07.1.1 — Таблица моделей

```gherkin
Given за 30d использовалось 6 разных моделей
When открыта вкладка "Models"
Then таблица: Provider, Model, Requests, Tokens, Cost, Avg latency, Error rate, Main users (top-3)
And строки отсортированы по Cost desc
```

**Требования:**

- **FR-07.1.1.1** — Сервис `get_models_breakdown(period)` возвращает таблицу по моделям + top-3 пользователей по `cost desc`.
- **FR-07.1.1.2** — `error_rate = failed_requests / total_requests`, при `total_requests == 0` возвращает `None`.
- **FR-07.1.1.3** — Цены моделей берутся из таблицы `model_prices`, версионируются по дате.

---

## F-08 — Alerts

### US-08.1 — Управление алертами

> *As an* Ops manager
> *I want* видеть и настраивать правила алертов и получать уведомления
> *so that* реагировать на риски и переборы бюджета быстро.

#### SC-08.1.1 — Таблица алертов

```gherkin
Given в БД есть 3 активных алерта разной severity
When открыта вкладка "Alerts"
Then таблица: Created, Type, Severity, Subject, Message, Status (new|ack|resolved)
And есть фильтры по severity и status
```

**Требования:**

- **FR-08.1.1.1** — Engine `evaluate_alert_rules()` запускает все активные правила и пишет новые алерты в таблицу `alerts`, не дублируя по уникальному `dedup_key`.
- **FR-08.1.1.2** — Поддерживаемые правила (минимум): `user_daily_spend > 50`, `team_monthly_budget_exceed > 80%`, `inactive_paid_seat > 14d`, `ai_code_pct_in_critical > 60`, `pr_ai_code_pct > 80 AND no_human_review`, `provider_usage_spike > 3x_avg`.
- **FR-08.1.1.3** — Severity: `critical|high|medium|low` зашиты в правиле.
- **FR-08.1.1.4** — UI поддерживает изменение статуса алерта `new → ack → resolved`.

---

## F-09 — Settings & Connectors

### US-09.1 — Подключение источников

> *As an* Admin
> *I want* подключить ключи OpenAI / Anthropic / GitHub в одном месте
> *so that* запустить синк без редактирования файлов вручную.

#### SC-09.1.1 — Сохранение credentials

```gherkin
Given открыта страница "Settings"
When пользователь вводит OpenAI API key и нажимает "Save"
Then ключ сохраняется в .streamlit/secrets.toml путь, валидируется через ping-запрос
And в UI отображается статус "connected"
```

**Требования:**

- **FR-09.1.1.1** — Поддержка трёх коннекторов с интерфейсом `Connector(test_connection() → bool, sync(period) → SyncReport)`.
- **FR-09.1.1.2** — Секреты не сохраняются в БД и не логируются.
- **NFR-09.1.1.1** — При отсутствии ключа коннектор работает в режиме `mock=True` и читает seed-данные.

---

## F-10 — Navigation & Theme

### US-10.1 — Бренд и навигация

> *As a* любой пользователь
> *I want* видеть знакомую визуальную идентичность HMND и быструю навигацию
> *so that* не путаться и быстро переходить между разделами.

#### SC-10.1.1 — Боковая навигация

```gherkin
Given любая страница дашборда
When пользователь смотрит на левый сайдбар
Then видно меню: Overview, Costs, Seats, Developers, Repositories, PR Quality, Models, Alerts, Settings
And в шапке логотип HMND и название "AI Governance Dashboard"
```

**Требования:**

- **FR-10.1.1.1** — Навигация реализована через Streamlit multi-page (`pages/` каталог).
- **NFR-10.1.1.1** — Палитра соответствует Humanoid: navy `#06091c`, blue `#4953d8`, line `#e8edf3`.
- **NFR-10.1.1.2** — Шрифт Inter, как в брендбуке.

---

## Сводная карта тестов → требования

Каждый тест в `tests/` именуется `test_<req_id_lower>` и проверяет ровно одно требование.

| Тест файла | Требование |
|------------|------------|
| `tests/test_overview.py::test_fr_01_1_1_1_kpi_keys` | FR-01.1.1.1 |
| `tests/test_overview.py::test_fr_01_1_1_2_zero_users` | FR-01.1.1.2 |
| `tests/test_overview.py::test_fr_01_1_1_3_delta_calc` | FR-01.1.1.3 |
| `tests/test_overview.py::test_nfr_01_1_1_1_perf_100k` | NFR-01.1.1.1 |
| `tests/test_overview.py::test_fr_01_1_2_1_provider_filter` | FR-01.1.2.1 |
| `tests/test_overview.py::test_fr_01_1_2_2_team_filter` | FR-01.1.2.2 |
| `tests/test_costs.py::test_fr_02_1_1_1_user_costs_shape` | FR-02.1.1.1 |
| `tests/test_costs.py::test_fr_02_1_1_2_limit_status` | FR-02.1.1.2 |
| `tests/test_costs.py::test_fr_02_1_2_1_spike_detection` | FR-02.1.2.1 |
| `tests/test_seats.py::test_fr_03_1_1_1_summary_keys` | FR-03.1.1.1 |
| `tests/test_seats.py::test_fr_03_1_1_4_recommendation` | FR-03.1.1.4 |
| `tests/test_devs.py::test_fr_04_1_1_2_ai_code_pct` | FR-04.1.1.2 |
| `tests/test_repos.py::test_fr_05_1_1_3_risk` | FR-05.1.1.3 |
| `tests/test_pr_quality.py::test_fr_06_1_1_1_risk_score` | FR-06.1.1.1 |
| `tests/test_models.py::test_fr_07_1_1_2_error_rate` | FR-07.1.1.2 |
| `tests/test_alerts.py::test_fr_08_1_1_1_dedup` | FR-08.1.1.1 |
| `tests/test_alerts.py::test_fr_08_1_1_2_rules_set` | FR-08.1.1.2 |

## Архитектура слоёв

### Data layer (`/data`)
- `schema.sql` — DDL для всех таблиц
- `db.py` — connection helper, миграции
- `models.py` — typed dataclasses
- `seed.py` — генератор демо-данных
- `connectors/openai.py`, `anthropic.py`, `github.py` — коннекторы с mock-режимом

### Backend layer (`/backend`)
- `services/overview.py` (FR-01.*)
- `services/costs.py` (FR-02.*)
- `services/seats.py` (FR-03.*)
- `services/developers.py` (FR-04.*)
- `services/repos.py` (FR-05.*)
- `services/pr_quality.py` (FR-06.*)
- `services/models_svc.py` (FR-07.*)
- `services/alerts.py` (FR-08.*)
- `analytics.py` — общие aggregations и helpers

### Frontend layer (`/frontend`)
- `app.py` — entry point, роутинг и общие стили (Overview)
- `theme.py` — палитра, CSS-инъекция в стиле HUMANOID
- `components.py` — KPI-карточки, бейджи, фильтры
- `pages/` — отдельные экраны (multi-page)
