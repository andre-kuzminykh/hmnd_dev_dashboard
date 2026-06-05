# Legacy features — F-02 through F-09

> **Status:** ARCHIVED. These specs describe pages from the original multi-page architecture (Streamlit `pages/`). The current single-page architecture (`frontend/main.py`) renders only Executive Overview (F-01) and AI Tools (F-12). Their backend services and test files still exist and pass — they just aren't reachable from the live UI.
>
> Restoring any of these to the live dashboard means:
> 1. Add a new section/tab to `frontend/sections/ai_tools.py` (or revive `frontend/sections/<name>.py`).
> 2. Wire it into `frontend/main.py`.
> 3. Move the F-NN section back to `docs/SPEC.md` and move its test-trace rows back too.

---

## ID conventions (see main `docs/SPEC.md`)

`F-XX` Feature · `US-XX.Y` User Story · `SC-XX.Y.Z` BDD Scenario · `FR-XX.Y.Z.N` Functional Requirement · `NFR-XX.Y.Z.N` Non-functional Requirement.

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

> **Note (current architecture):** Models are now surfaced as part of the AI Tools `Models` tab (F-12). The cross-provider model landscape, per-tool model usage, and top-spender-per-model views live there. The legacy `get_models_breakdown()` service is still imported by `frontend/sections/ai_tools.py` for the per-model spend table.

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

> **Note (current architecture):** Credentials are now configured via `.env` (consumed by `backend/config.py:load_config`). The `connectors/openai.py`, `anthropic_json.py`, `cursor_json.py` loaders use them on startup; the sync sidecar runs `scripts/sync.py` every 15 min. There is no in-UI Settings page.

---

## Test traceability (legacy)

The tests below still run as part of `pytest` and remain green. They were originally moved here together with the feature sections to keep `docs/SPEC.md` focused on shipped UI.

| Test file | Requirement |
|------------|------------|
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

## Service / section files (legacy)

These exist in code; their tests pass; they aren't loaded by `frontend/main.py`:

| File | Spec ref |
|------|----------|
| `frontend/sections/costs.py` + `backend/services/costs.py` | F-02 |
| `frontend/sections/seats.py` + `backend/services/seats.py` | F-03 |
| `frontend/sections/developers.py` + `backend/services/developers.py` | F-04 |
| `frontend/sections/repositories.py` + `backend/services/repos.py` | F-05 |
| `frontend/sections/pr_quality.py` + `backend/services/pr_quality.py` | F-06 |
| `frontend/sections/models.py` (note: `backend/services/models_svc.py` IS used by current AI Tools tab) | F-07 |
| `frontend/sections/alerts.py` + `backend/services/alerts.py` | F-08 |
| `frontend/sections/settings.py` | F-09 |
| `frontend/sections/api_keys.py` + `backend/services/api_keys.py` | (related to F-13 API-key drill-down; service still used) |
| `frontend/sections/insights.py` + `backend/services/insights.py` | (legacy insights page) |
| `frontend/sections/projects.py` + `backend/services/openai_projects.py` | (related to F-13 project drill-down) |
