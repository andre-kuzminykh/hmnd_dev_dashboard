# HMND AIOps Dashboard — Specification

> Источник правды для разработки. Иерархия: **Feature → User Flow → Use Case → Requirements (FR/NFR) → Tests by layer**.
>
> **Documentation migration policy (введено 2026-05-16, lazy):**
> - Features F-01 … F-16 — старый формат `Feature → US → BDD → FR/NFR → Tests`. Не переписываются массово.
> - Features F-17 + — новый формат `Feature → UF → UC → FR/NFR → Tests-by-layer` (см. F-17 как образец).
> - Любая фича, которую трогаем после 2026-05-16, **переписывается** в новый формат в том же PR. Это даёт постепенную миграцию без big-bang rewrite.
> - Тесты раскладываются на 4 уровня: **T-INFRA** (env/files/auth) · **T-DATA** (format/parsing/schema) · **T-SVC** (business logic) · **T-AI** (prompts/agents).

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

## F-12 — AI Tools Dashboard

**Цель:** Tool-centric экран для CTO/Eng-Manager: одной страницей с табами свести Claude / ChatGPT / Cursor + cross-provider High Spenders. Параллельный взгляд к F-01 Overview, но в разрезе **инструментов**, а не KPI-карточек.

### US-12.1 — Tabs across tools

> *As an* Engineering manager
> *I want* видеть AI-расход и активность в разрезе инструментов (Claude / ChatGPT / Cursor) и отдельный таб High Spenders
> *so that* отвечать на вопросы «кто пользуется чем и сколько тратит» без переключения между страницами.

#### SC-12.1.1 — Overview tab + freshness header

```gherkin
Given в БД есть usage_events за последние 5 дней по как минимум одному провайдеру
When пользователь открывает "AI Tools" → Overview tab
Then над табами рендерится строка freshness: "Claude: <start>–<end> · <source>" по каждому провайдеру
And в правом верхнем углу видны 3 цветных бейджа: Claude (фиолетовый), ChatGPT (зелёный), Cursor (янтарный)
And в табе Overview ровно 4 KPI-карточки: Claude Chat Users (5d), Claude Code Users (5d), ChatGPT Active Users, Cursor Active Devs
```

**Требования:**

- **FR-12.1.1.1** — Сервис `get_provider_freshness()` возвращает dict `{provider → {start_date, end_date, source}}`, где `source ∈ {'real','mock','absent'}`.
- **FR-12.1.1.2** — Сервис `get_ai_tools_overview(period_days=5)` возвращает 4 ключа: `claude_chat_users`, `claude_code_users`, `chatgpt_active_users`, `cursor_active_devs`. Поля без подключенного источника возвращают `None`.
- **FR-12.1.1.3** — `source = 'mock'` если у провайдера есть хотя бы один `api_keys.external_id LIKE 'sk-ant-mock-%'` или `'sk-mock-%'`. `source = 'real'` если есть real ключ. `source = 'absent'` если нет ни одного.
- **NFR-12.1.1.1** — Цветовая палитра: Claude = `#6366f1`, ChatGPT = `#10a37f`, Cursor = `#f59e0b`.

#### SC-12.1.2 — Claude Users tab

```gherkin
Given Anthropic usage events в БД
When открыта вкладка Claude Users
Then 4 KPI: Chat Active Users, Total Messages, Claude Code Users, CC Lines Added
And список Top 10 by Messages с горизонтальными фиолетовыми баром
And полная таблица All Claude Users с колонками: Name, Messages, CC Sessions, Lines Added, Commits
And отсутствующие данные (CC Sessions / Lines / Commits) рисуются как тире
```

**Требования:**

- **FR-12.1.2.1** — `get_users_for_provider(provider, period_days)` возвращает per-user roll-up: `{user_name, messages, sessions, lines_added, commits, cost}`. `messages = COUNT(usage_events)`.
- **FR-12.1.2.2** — `sessions / lines_added / commits = None` пока не подключены Claude Code telemetry / GitHub.
- **FR-12.1.2.3** — UI скрывает пустые ячейки тире (`—`).

#### SC-12.1.3 — ChatGPT Users tab

```gherkin
Given OpenAI usage events
When открыта вкладка ChatGPT Users
Then 4 KPI: Active Users, Total Messages, Total Spend, High Spenders count (≥$200)
And полная таблица All ChatGPT Users (Name, Messages, Spend, Flag)
```

**Требования:**

- **FR-12.1.3.1** — `get_users_for_provider("openai", period_days)` возвращает `cost` поле.
- **FR-12.1.3.2** — Колонка Flag: `High` если spend ≥ $1000, `Medium` если ≥ $500, `Watch` если ≥ $200, иначе пусто.

#### SC-12.1.4 — Cursor placeholder

```gherkin
Given Cursor не подключен
When открыта вкладка Cursor
Then показано пустое состояние "Connect Cursor Teams API"
And никаких пустых KPI или таблиц не отрисовано
```

**Требования:**

- **FR-12.1.4.1** — Cursor статус определяется по наличию env `CURSOR_API_TOKEN` (`load_config().cursor_token`); при отсутствии — placeholder.

#### SC-12.1.5 — High Spenders tab

```gherkin
Given несколько пользователей с расходом ≥ $200 за период
When открыта вкладка High Spenders
Then 3 KPI: count, Combined Spend, Top Spender (имя + сумма)
And горизонтальные бары с цветом по риску: Red ≥ $1000, Amber ≥ $500, Yellow ≥ $200
And подробная таблица: Name, Messages, Spend, $/msg, Risk
And строка spend подкрашена тем же цветом, что и бейдж Risk
```

**Требования:**

- **FR-12.1.5.1** — `get_high_spenders(period_days=30, threshold=200)` cross-provider, отсортировано по `spend desc`.
- **FR-12.1.5.2** — Risk-классификация: `high` если spend ≥ $1000, `medium` если ≥ $500, `low` если ≥ $200, иначе не попадает.
- **FR-12.1.5.3** — `dollar_per_msg = spend / messages` округлено до 2 знаков; при `messages == 0` возвращает `None`.
- **NFR-12.1.5.1** — Цвета риска: red `#ef4444`, amber `#f59e0b`, yellow `#eab308`.



### US-10.1 — Бренд и навигация

> *As a* любой пользователь
> *I want* видеть знакомую визуальную идентичность HMND и быструю навигацию
> *so that* не путаться и быстро переходить между разделами.

#### SC-10.1.1 — Боковая навигация

```gherkin
Given любая страница дашборда
When пользователь смотрит на левый сайдбар
Then видно меню: Overview, Costs, Seats, Developers, Repositories, PR Quality, Models, Alerts, Settings
And в шапке логотип HMND и название "AIOps Dashboard"
```

**Требования:**

- **FR-10.1.1.1** — Навигация реализована через Streamlit multi-page (`pages/` каталог).
- **NFR-10.1.1.1** — Палитра соответствует Humanoid: navy `#06091c`, blue `#4953d8`, line `#e8edf3`.
- **NFR-10.1.1.2** — Шрифт Inter, как в брендбуке.

---

## F-13 — Advanced filters (date range, API key, project)

**Цель:** Привести панель фильтров к уровню OpenAI Usage UI: верхним уровнем выбирается провайдер, дата задаётся календарём с пресетами, есть drill-down по API-ключу и (когда подключим) по проекту. Все аналитические сервисы должны принимать эти фильтры единообразно.

### US-13.1 — Date range with presets

> *As a* любой пользователь
> *I want* выбирать произвольный промежуток дат или один из пресетов одной кнопкой
> *so that* быстро сравнивать «вчера vs сегодня» или «неделя vs прошлая неделя» без правки кода.

#### SC-13.1.1 — Custom range через календарь

```gherkin
Given открыта любая аналитическая страница
When пользователь выбирает диапазон 2026-04-15 — 2026-04-22 в date_input
Then KPI и графики пересчитываются по событиям с occurred_at в этом диапазоне
And фильтр period сбрасывается в значение "Custom"
```

**Требования:**

- **FR-13.1.1.1** — `Filters.date_from`, `Filters.date_to: Optional[datetime]`. Когда оба заданы — приоритет над `period_days`.
- **FR-13.1.1.2** — `Filters.date_range(now)` возвращает явный диапазон если задан, иначе вычисляет от `period_days`.
- **FR-13.1.1.3** — UI кладёт диапазон в `st.session_state.date_range` и помечает period-пресет как `Custom`.

#### SC-13.1.2 — Пресеты одной кнопкой

```gherkin
When пользователь нажимает "Last 7 days"
Then фильтр period_days переключается на 7
And date_from/date_to очищаются
And все страницы пересчитывают данные за 7 дней
```

**Требования:**

- **FR-13.1.2.1** — Пресеты: `Today`, `Yesterday`, `Week to date`, `Month to date`, `Last 7 days`, `Last 14 days`, `Last 30 days`, `Last 90 days`, `Custom`.
- **FR-13.1.2.2** — `Today/Yesterday` ставят date_from=date_to (один день).
- **FR-13.1.2.3** — `Week to date` от понедельника текущей недели до сегодня.
- **FR-13.1.2.4** — `Month to date` от первого числа текущего месяца до сегодня.

### US-13.2 — Provider primary + API key drill-down

> *As a* finance/ops пользователь
> *I want* сначала выбирать провайдера, потом конкретный API ключ и видеть весь дашборд только по этому срезу
> *so that* находить «кто жжёт через ключ X» в любой панели.

#### SC-13.2.1 — API key dropdown

```gherkin
Given в БД есть api_keys для провайдера 'openai'
When пользователь в filters bar выбирает ключ 'n8n_artem'
Then все KPI / таблицы / графики на странице фильтруются по этому api_key_id
And в session_state хранится {api_key_id: <id>}
```

**Требования:**

- **FR-13.2.1.1** — `Filters.api_key_id: Optional[int]`. Все сервисы добавляют `WHERE api_key_id = ?` если задан.
- **FR-13.2.1.2** — Список ключей в dropdown берётся из `api_keys` для выбранного провайдера; элементы сортируются по `last_used_at desc`.
- **FR-13.2.1.3** — Item label: `name · redacted`.

### US-13.3 — Project drill-down

> *As a* admin
> *I want* фильтровать данные по OpenAI project'у
> *so that* видеть отдельно расход CEO Brain / n8n_artem / typingmind.

#### SC-13.3.1 — Project filter

```gherkin
Given OpenAI sync подтянул проекты через /v1/organization/projects
When пользователь выбирает проект "CEO Brain"
Then фильтр применяется ко всем расчётам
```

**Требования:**

- **FR-13.3.1.1** — Таблица `projects (id, provider_id, external_id, name)` + колонка `project_id` на `usage_events` и `api_keys`.
- **FR-13.3.1.2** — `Filters.project_id: Optional[int]`. Все сервисы добавляют `WHERE project_id = ?`.
- **FR-13.3.1.3** — Sync OpenAI пулит `/v1/organization/projects` и группирует usage по `group_by=project_id`.

---

## F-14 — Multi-source data ingestion (API + JSON)

**Цель:** Дашборд должен получать данные из двух типов источников:
* **API push** — там где у нас есть admin-ключ (OpenAI, в будущем Anthropic Admin API).
* **JSON pull из репо** — там где доступа к API нет: пользователь кладёт файл `<Provider>_YYYYMMDD.json` в `sources/`, дашборд **сам** подхватывает самый свежий и обновляет данные.

### US-14.1 — JSON files как авторитетный источник

> *As a* admin without provider Admin API access
> *I want* положить JSON-файл с user/spend разбивкой в репо
> *so that* дашборд сразу покажет реальные данные без коммита кода.

#### SC-14.1.1 — Anthropic JSON

```gherkin
Given в sources/ лежит Anthropic_20260515.json по схеме F-14.1.1
When дашборд / sync рендерится
Then в usage_events создаются строки для каждого user × product (chat / claude_code / cowork_other)
And cost_usd распределяется пропорционально из products[].spend_usd
And models таблица обновляется списком из models[]
```

**Требования:**

- **FR-14.1.1.1** — Схема Anthropic JSON документирована в `docs/SOURCES_SCHEMA.md`. Обязательные ключи: `period_start`, `period_end`, `users[]`, `products{}`, `models[]`.
- **FR-14.1.1.2** — Loader `load_anthropic_json(path)` идемпотентен — DELETE-then-INSERT per period.
- **FR-14.1.1.3** — Если для одного провайдера в `sources/` несколько файлов, побеждает **самый свежий по дате в имени**.
- **FR-14.1.1.4** — Loader auto-discovery: pattern `Anthropic*_YYYYMMDD.json` (с трейлинговой `s` тоже принимается — `Anthropics_*`).

#### SC-14.1.2 — Cursor JSON

```gherkin
Given Cursor_20260515.json по схеме F-14.1.2
When дашборд читает sources
Then leaderboard данные подменяют CSV из data_ne/ (JSON priority)
```

**Требования:**

- **FR-14.1.2.1** — Loader `load_cursor_json(path)` принимает users + models + summary.
- **FR-14.1.2.2** — Если JSON и CSV конфликтуют — JSON приоритетнее (свежее и финальный snapshot вендора).

### US-14.2 — API источник: OpenAI multi-org

> *As an* admin с двумя OpenAI организациями (Artem + Humanoid)
> *I want* положить оба admin-ключа в `OPENAI_API_KEYS` и видеть данные обеих org-ов в одном дашборде
> *so that* не переключаться между источниками вручную.

#### SC-14.2.1 — Multi-org sync

```gherkin
Given OPENAI_API_KEYS = [{label:Artem,key:...},{label:Humanoid,key:...}]
When run_sync()
Then для каждого ключа создаётся локальная organizations строка
And usage_events помечаются organization_id для filter по org
```

**Требования:**

- **FR-14.2.1.1** — Loader пропускает Org admin-key (`sk-admin-...`); project keys (`sk-proj-...`) идут в отдельный `OPENAI_PROJECT_KEYS` (inventory only).
- **FR-14.2.1.2** — `organizations` таблица + `organization_id` колонка на `usage_events / api_keys / users`.
- **FR-14.2.1.3** — UI фильтр Org позволяет смотреть данные одной org или All.

### US-14.3 — Приоритет JSON over API при дублировании

> *As an* admin
> *I want* при наличии JSON-файла и API данных за тот же период видеть JSON
> *so that* JSON всегда отражает финальное состояние (вендор UI), а API может отставать.

#### SC-14.3.1 — JSON для Anthropic вместо cursor-derived

```gherkin
Given sources/Anthropic_20260515.json существует
And data/cursor_to_anthropic.derive_anthropic_from_cursor() даёт другие цифры
When run_sync()
Then JSON loader выполняется первым
And cursor-derived skipped с пометкой "skipped: JSON source present"
```

**Требования:**

- **FR-14.3.1.1** — В run_sync для каждого провайдера: scan `sources/`, если JSON найден — используй его и пропусти fallback path.

---

## F-15 — Code Quality (Git × AI)

**Цель:** Ответить CEO/CTO на вопрос «сколько багов от ИИ и сколько люди делают». Из коммитов 3 репозиториев (`hmnd` / `hmnd-cloud` / `hmnd-sim`) — по regex на subject — классифицируем bug-fix / revert / feature / refactor / test / docs, и сводим в команду-вайд rates + per-author breakdown + AI-spend-per-fix debt indicator + high-churn files.

### US-15.1 — Bug-fix rate across team and AI/human split

> *As a* CEO/CTO
> *I want* видеть какой % коммитов — это баг-фиксы, в разрезе людей vs ботов/AI-агентов, и сколько денег уходит на каждый bug-fix
> *so that* понимать, не генерит ли AI код, который потом приходится постоянно чинить.

#### SC-15.1.1 — Subject classification at load time

```gherkin
Given в sources/ лежит git_commit_file_stats_YYYYMMDD.csv с per-commit-file rows
When запускается load_git_commits_csv(path)
Then для каждого уникального (repo, sha) пишется строка в git_commits с flags is_bug_fix / is_revert / is_feature / is_refactor / is_test / is_docs (0|1)
And классификация делается regex по полю subject (первая строка сообщения коммита)
And автор-бот (github-actions, Cursor Agent, etc) помечается is_bot=1 через _is_bot_author
And user_id заполняется по результату _match_user_id (email / full_name / local-part)
```

**Требования:**

- **FR-15.1.1.1** — `_classify_subject(subject)` возвращает dict с 6 флагами по regex:
  - `is_bug_fix` если subject матчит `\b(fix|fixes|fixed|bug|bugfix|hotfix|patch)\b` или `^fix[:\(!]`
  - `is_revert` если матчит `^revert\b` или `\brevert[:\s\"\']`
  - `is_feature` если `^feat\b`, `^feature\b`, или `\badd(ed|s)?\b\s`
  - `is_refactor` если `^refactor\b`, `\brefactor(ing|ed)?\b`, `^style\b`, `^perf\b`, `^chore\b`
  - `is_test` если `^test\b` или `\btest(s|ing)?\b`
  - `is_docs` если `^docs?\b` или `\b(documentation|readme)\b`
  - Пустая / None строка → все 0.
- **FR-15.1.1.2** — `load_git_commits_csv` пишет в `git_commits` одну строку на (repo, sha) с агрегированными additions/deletions/files_changed по всем file-rows и тегами из `_classify_subject`. Перед записью таблица очищается (idempotent).

#### SC-15.1.2 — Team-wide bug-rate rollup

```gherkin
Given в git_commits 10 коммитов: 3 fix + 7 feat, все за последние 30 дней
When вызван get_team_quality(period_days=30)
Then commits = 10, fixes = 3, features = 7
And bug_rate_pct = 30.0, revert_rate_pct = 0.00
And если 4 коммита человеческих (1 fix) + 2 коммита бота (1 fix) — human_bug_rate_pct=25.0, bot_bug_rate_pct=50.0
```

**Требования:**

- **FR-15.1.2.1** — `get_team_quality(period_days, repos)` возвращает dict с полями: `commits, fixes, reverts, features, refactors, tests, docs, bot_commits, human_commits, bug_rate_pct, revert_rate_pct, human_bug_rate_pct, bot_bug_rate_pct, additions, deletions`. Все percent-поля округлены до 1 знака (revert до 2).
- **FR-15.1.2.2** — Human vs bot split: `human_commits = SUM(is_bot=0)`, `bot_commits = SUM(is_bot=1)`, и аналогично для fixes. Bug-rate считается per cohort.
- **FR-15.1.2.3** — Repo filter: при `repos=["hmnd"]` SQL подмешивает `AND c.repo IN (?)` — все агрегаты считаются по подмножеству.
- **FR-15.1.2.4** — Date filter: `period_days > 0` → `WHERE substr(c.author_date, 1, 10) >= cutoff`. `period_days = 0` — фильтр выключен.
- **FR-15.1.2.5** — Empty result: если в скоупе 0 коммитов — возвращает все нули + `bug_rate_pct = None` (не делим на 0), без NaN.

#### SC-15.1.3 — Per-author breakdown with alias dedup

```gherkin
Given user 'Alice' с user_id=42; в git_commits 2 коммита от 'Alice' и 1 от alias 'alice2', все с user_id=42
When вызван get_quality_per_author(period_days=30)
Then Alice появляется ровно в одной строке (GROUP BY COALESCE(user_id, author_name))
And commits = 3, fixes = соответствует ground truth
And bug_rate_pct = fixes / commits * 100, округлено до 1 знака
```

**Требования:**

- **FR-15.1.3.1** — Per-author rollup группируется по `COALESCE(c.user_id, c.author_name)` — алиасы одного человека (один user_id) сливаются в одну строку. canonical_name = `COALESCE(u.full_name, c.author_name)`.

#### SC-15.1.4 — AI spend per bug-fix debt indicator

```gherkin
Given за период $100 AI spend в usage_events и 4 коммита с is_bug_fix=1
When вызван get_ai_spend_per_fix(period_days=30)
Then ai_spend = 100.0, fixes = 4, ai_spend_per_fix = 25.0
And если fixes = 0 → ai_spend_per_fix = None (не падаем DivisionByZero)
```

**Требования:**

- **FR-15.1.4.1** — `get_ai_spend_per_fix(period_days)` делает single SQL с двумя subselects (`SUM(cost_usd)` из `usage_events`, `COUNT(*)` из `git_commits WHERE is_bug_fix=1`) и возвращает `{period_days, ai_spend, fixes, ai_spend_per_fix}`.
- **FR-15.1.4.2** — Zero-fixes safety: `_safe_div(spend, 0) → None`.
- **FR-15.1.4.3** — `get_ai_spend_per_fix(period_days, repos=[...])` сужает знаменатель (bug-fixes) к выбранным репо. Числитель (AI spend) остаётся team-wide потому что у `usage_events` нет колонки repo. UI это явно описывает в help-tooltip. Контракт: при `repos=['hmnd']` fixes считаются только из коммитов в hmnd.

#### SC-15.2.2 — Empty-scope explicit message

```gherkin
Given пользователь выбрал репо hmnd-sim в Devs табе
And за 90 дней в git_commits для hmnd-sim 0 строк (например, hmnd-sim архивный)
When секция Code Quality рендерится
Then заголовок 'Code Quality (Git × AI)' виден всегда
And если commits=0 — рендерится st.info с текстом 'No commits in selected repos within last N days. Either widen the period or pick different repos.'
And info упоминает что сегментные таблицы выше показывают LIFETIME коммиты, а Code Quality period-filtered — это объясняет несоответствие
```

**Требования:**

- **FR-15.2.2.1** — `if tq["commits"] == 0:` не скрывать секцию, рендерить explicit info-блок с указанием выбранного скоупа (репо + период) и причины расхождения с per-author таблицами.

#### SC-15.1.5 — High-churn files (problem areas)

```gherkin
Given в per-commit-file CSV файл auth.py меняли в 3 разных коммитах, util.py — в 1
When вызван get_high_churn_files(period_days=30, limit=10)
Then auth.py первый в списке с commits=3, util.py — второй с commits=1
And по каждому файлу: file, commits, additions, deletions, repos (';'-separated)
And при repos=["hmnd"] — учитываются только коммиты из hmnd
```

**Требования:**

- **FR-15.1.5.1** — `get_high_churn_files(period_days, repos, limit)` НЕ читает БД (`git_commits` collapses per-commit), а runtime-читает per-commit-file CSV через `latest_git_commits_file()`. Если CSV отсутствует — `[]`.
- **FR-15.1.5.2** — Repo filter работает над raw CSV: строки с `repo not in repos_set` пропускаются.
- **FR-15.1.5.3** — `period_days=0` или > 9999 ⇒ дата-фильтр выключен (all-time), как в `_date_filter_sql`. До фикса значение 0 устанавливало `cutoff=today` и отсекало всё кроме сегодняшних коммитов.

### US-15.2 — UI: Code Quality block in Devs tab

> *As a* CEO
> *I want* увидеть весь Code Quality на одном экране в табе Devs (Git × AI), ВЫШЕ детальных per-segment таблиц
> *so that* команда-вайд signal читается до того, как я уйду в детали по людям.

#### SC-15.2.1 — Block placement and structure

```gherkin
Given get_team_quality вернул commits > 0
When открыт таб 'Devs (Git × AI)'
Then секция 'Code Quality (Git × AI)' рендерится ПОСЛЕ Segment distribution + ПЕРЕД 'Drill into segments'
And в секции по порядку: KPI row → Commit composition bar → 2-column ($/fix card + AI vs human bug rate bars) → Per-author bug-fix breakdown table → High-churn files table
And KPI row содержит 5 карточек: Commits / Bug-fix rate / Human bug rate / Bot bug rate / Revert rate
And $/fix card цвет границы: зелёный (< $100), оранжевый ($100-500), красный (≥ $500)
And если commits = 0 — вся секция скрыта целиком (нет 'Code Quality' заголовка, нет пустых таблиц)
```

**Требования:**

- **FR-15.2.1.1** — UI-секция respects period + repo multi-select из Devs табa.

---

## F-16 — '?' help tooltips on KPIs and section titles

**Цель:** Сделать дашборд читаемым для не-технического CEO. Каждая важная метрика и каждая секция имеет тонкий '?' значок, по hover-у которого появляется короткое (1-3 строки) объяснение «что это · почему важно · когда тревожиться» на русском.

### US-16.1 — Help icon on section() and kpi_row()

> *As a* CEO who didn't write this dashboard
> *I want* hover-tooltip с объяснением каждого KPI и заголовка секции
> *so that* мне не приходится спрашивать «а что это значит» каждый раз.

#### SC-16.1.1 — Help icon rendering

```gherkin
Given вызов section(title="Code Quality", help="Качество кода через призму AI")
When страница отрисована
Then в HTML заголовка появляется <span class="hmnd-help" data-tip="Качество кода через призму AI" tabindex="0">?</span>
And при hover/focus открывается CSS popover с тем же текстом

Given вызов kpi_row([{label, value, help}, ...])
When страница отрисована
Then каждая KPI-карточка с help-полем имеет '?' значок рядом с label
And карточки без help-поля рендерятся БЕЗ '?' (no broken DOM)
```

**Требования:**

- **FR-16.1.1.1** — `frontend.components.section(title, help=None)` — при `help is not None` добавляет `_help_icon(help)` в HTML заголовка.
- **FR-16.1.1.2** — `frontend.components.kpi_card(label, value, ..., help=None)` принимает help-поле; `kpi_row(items)` пробрасывает help в каждый kpi_card.
- **FR-16.1.1.3** — `_help_icon(text)` экранирует `& < > "` чтобы текст с тегами/кавычками не ломал атрибут `data-tip` и обрамляющий HTML. Возвращает `""` для `None` / пустой строки — безопасно сплайсить unconditionally.
- **FR-16.1.1.4** — Отсутствие `help` параметра должно давать пустой результат (`_help_icon(None) == ""`) — обратная совместимость для всех существующих `section("...")` без help.

#### SC-16.1.2 — Accessibility

```gherkin
Given '?' значок в DOM
When юзер табает к нему клавиатурой
Then значок фокусируется (tabindex=0) и тот же tooltip открывается через :focus
And значок имеет aria-label с тем же текстом для screen reader
```

**Требования:**

- **FR-16.1.2.1** — `_help_icon` рендерит `tabindex="0" aria-label="<text>"` чтобы быть keyboard-accessible и читаемым assistive-tech.

---

## F-17 — Configurable repository list for git extraction

**Цель:** Дать админу возможность расширить набор репо, по которым `scripts.extract_git_stats` собирает CSV для дашборда, **без правки кода**. Report II identified ~10 active first-party engineering repos beyond the 3 monorepos (firmware, drivers, hm-ops, etc.) — конфигурируемый список позволяет включать их в productivity-метрики по необходимости.

> **Новый формат документации (введён в F-17, применяется ко всем фичам):**
> `Feature → User Flow → Use Case → FR/NFR → Tests`, где **тесты раскладываются на 4 уровня**:
> - **Infra** (T-INFRA-...) — окружение: env vars, файлы, permissions, network/auth
> - **Data** (T-DATA-...) — формат данных: schema, parsing, CSV/JSON contracts
> - **Service** (T-SVC-...) — бизнес-логика: чистые функции, формулы, сервисный layer
> - **AI/Prompts** (T-AI-...) — LLM-related: prompt templates, agent instructions (n/a for F-17)
>
> Один FR может покрываться несколькими T-LEVEL тестами разных уровней (e.g. infra + service).

---

### UF-17.1 — User Flow: Admin расширяет scope аудита без правки кода

> *As an* admin (Engineering Ops)
> *I want* указать список репозиториев для git-extraction через config-файл / env-переменную / CLI-флаг
> *so that* я могу включать новые репо в дашборд за минуту, не открывая редактор и не делая PR.

**Шаги flow:**
1. Admin решает добавить новый репо (например `HumanoidTeam/hm-ops`) в дашборд.
2. Admin либо раскомментирует строку в `sources/git_repos.txt`, либо передаёт `--repos` / `HMND_GIT_REPOS`.
3. Запускает `docker compose exec dashboard python -m scripts.extract_git_stats`.
4. Скрипт читает источник списка по приоритету, клонирует/обновляет каждый репо, пишет CSV.
5. Sync sidecar (или admin вручную) загружает CSV в `git_commits` / `git_authors`.
6. Через 15 мин новый репо появляется в Repository dropdown'е дашборда.

#### UC-17.1.1 — Default fallback (no override)

```gherkin
Given нет ни `--repos`, ни env `HMND_GIT_REPOS`, ни файла `sources/git_repos.txt`
When запускается `python -m scripts.extract_git_stats`
Then скрипт использует built-in список из 3 репо: HumanoidTeam/{hmnd, hmnd-cloud, hmnd-sim}
And поведение идентично pre-F-17 версии — те же CSV-файлы, то же количество строк
```

**Требования:**
- **FR-17.1.1.1** — `scripts.extract_git_stats._resolve_repos(cli_arg)` возвращает list[str] согласно priority `CLI > env > config file > built-in default`.
- **FR-17.1.1.2** — Built-in `DEFAULT_REPOS` = `["HumanoidTeam/hmnd", "HumanoidTeam/hmnd-cloud", "HumanoidTeam/hmnd-sim"]` (3 элемента, тот же порядок, как до F-17).

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Service | `T-SVC-17.1.1.1` | `_resolve_repos(None)` без env/file → `DEFAULT_REPOS` |
| Service | `T-SVC-17.1.1.2` | `DEFAULT_REPOS` неизменяем (3 элемента, exact order) |
| Service | `T-SVC-17.1.1.3` | priority order: CLI > env > file > default (combo test) |
| Data | `T-DATA-17.1.1.1` | `DEFAULT_REPOS` валиден как формат `org/repo` (no slashes-elsewhere) |

#### UC-17.1.2 — CLI flag override

```gherkin
Given пользователь запускает `python -m scripts.extract_git_stats --repos "org/a,org/b,org/c"`
When _resolve_repos() вызывается
Then возвращает ["org/a", "org/b", "org/c"]
And env-переменная и config-файл игнорируются (даже если они заданы)
```

**Требования:**
- **FR-17.1.2.1** — `--repos "a/b,c/d"` парсится через split по запятой, whitespace по краям обрезается, пустые элементы выкидываются.
- **FR-17.1.2.2** — CLI значение имеет приоритет над env и config — если оно непустое (whitespace-only считается пустым).

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Service | `T-SVC-17.1.2.1` | parsing: `"  a/b ,c/d,, e/f "` → `["a/b","c/d","e/f"]` |
| Service | `T-SVC-17.1.2.2` | CLI beats env + file when CLI is non-empty |
| Service | `T-SVC-17.1.2.3` | empty CLI (`""` or whitespace) falls through to env/file/default |

#### UC-17.1.3 — Env var override

```gherkin
Given нет `--repos`, но установлен `HMND_GIT_REPOS="x/y, z/w"`
When _resolve_repos(None) вызывается
Then возвращает ["x/y", "z/w"]
And config-файл игнорируется
```

**Требования:**
- **FR-17.1.3.1** — `HMND_GIT_REPOS` parsing идентичен CLI (split по запятой, strip whitespace, skip empties).
- **FR-17.1.3.2** — Пустой env-var (`HMND_GIT_REPOS=""` или whitespace-only) триггерит fallback к config-файлу.

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Infra | `T-INFRA-17.1.3.1` | env var actually visible in process (`os.environ["HMND_GIT_REPOS"]` set in conftest) |
| Service | `T-SVC-17.1.3.1` | env parsing: `" x/y ,z/w , "` → `["x/y","z/w"]` |
| Service | `T-SVC-17.1.3.2` | empty env falls through to file/default |

#### UC-17.1.4 — Config file (`sources/git_repos.txt`)

```gherkin
Given нет `--repos`, нет env, но существует `sources/git_repos.txt` со строками:
  """
  # Production repos
  HumanoidTeam/hmnd
  HumanoidTeam/hmnd-cloud  # core infra (inline comment)

  #HumanoidTeam/disabled-fork
  HumanoidTeam/hm-ops
  """
When _resolve_repos(None) вызывается
Then возвращает ["HumanoidTeam/hmnd", "HumanoidTeam/hmnd-cloud", "HumanoidTeam/hm-ops"]
And строки-комментарии, inline `# ...` и пустые строки игнорируются
```

**Требования:**
- **FR-17.1.4.1** — Config-файл парсится построчно: всё после `#` отбрасывается, потом `.strip()`. Если результат непустой — добавляется в list. Поддерживает inline-комментарии.
- **FR-17.1.4.2** — Файл не обязателен. Если отсутствует или содержит только комментарии — fallback к built-in default.

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Infra | `T-INFRA-17.1.4.1` | `sources/git_repos.txt` exists in committed repo (smoke check) |
| Infra | `T-INFRA-17.1.4.2` | committed `git_repos.txt` content matches DEFAULT_REPOS + ≥ 9 active engineering |
| Data | `T-DATA-17.1.4.1` | parsing strips `#` (full-line + inline) + blanks |
| Data | `T-DATA-17.1.4.2` | every parsed line matches `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$` format |
| Service | `T-SVC-17.1.4.1` | missing file or all-comments file → fallback to DEFAULT_REPOS |

---

### UF-17.2 — User Flow: Resilience — failed clone не валит batch

> *As an* admin
> *I want* чтобы extraction завершилась даже если один репо недоступен (отозванный PAT, удалённый repo, network blip)
> *so that* я не теряю данные по 11 репо из-за одного broken'а.

#### UC-17.2.1 — Skip failed clone, continue with rest

```gherkin
Given в списке 5 репо, и 1 из них приватный без доступа PAT
When extract_git_stats запускается
Then 4 успешных репо обрабатываются как обычно
And скрипт печатает SKIPPED список с failed репо
And exit code = 0 (это не fatal)
```

**Требования:**
- **FR-17.2.1.1** — `_ensure_repo()` возвращает `None` при failed clone/fetch (не raise). Caller skip-ает `None` и продолжает.
- **FR-17.2.1.2** — В конце экстракции печатается SKIPPED список если он непуст; exit code = 0.
- **NFR-17.2.1.1** — Partial clones удаляются при failure (`rm -rf` target dir), чтобы следующий run мог retry чисто.

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Infra | `T-INFRA-17.2.1.1` | bad PAT → curl HTTP 404 reproducible (smoke; не запускается в CI) |
| Service | `T-SVC-17.2.1.1` | `_ensure_repo` returns None on subprocess non-zero (mocked) |
| Service | `T-SVC-17.2.1.2` | `main()` continues to next repo after skip; final report writes |

#### UC-17.2.2 — Repo identification (org/repo → short name)

```gherkin
Given строка "HumanoidTeam/firmware_hal_aurix_tc3"
When _ensure_repo() обрабатывает её
Then short_name = "firmware_hal_aurix_tc3" (всё после первого '/')
And `git_commits.repo` column в CSV содержит short_name, не full org/repo
```

**Требования:**
- **FR-17.2.2.1** — short name = `full_name.split("/", 1)[1]`. Для строк без '/' — skip с warning'ом (FR-17.2.1.1 path).
- **FR-17.2.2.2** — Существующие CSV-данные (3 default repos) под short names `hmnd`, `hmnd-cloud`, `hmnd-sim` остаются совместимы — никакого ре-export'а не требуется.

**Tests by layer:**

| Layer | Test ID | What it verifies |
|---|---|---|
| Data | `T-DATA-17.2.2.1` | short_name extraction: `"a/b"`→`"b"`, `"a/b/c"`→`"b/c"` (.split maxsplit=1) |
| Data | `T-DATA-17.2.2.2` | committed `git_repos.txt` имеет `hmnd, hmnd-cloud, hmnd-sim` в качестве short_name (backwards compat) |

---

Каждый тест в `tests/` именуется `test_<test_id_lower>` (e.g. `test_t_svc_17_1_1_1_default_fallback`) и проверяет ровно одно требование. Один FR может покрываться несколькими тестами разных уровней — это OK и желательно для critical features.

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
| `tests/test_ai_tools.py::test_fr_12_1_1_1_freshness` | FR-12.1.1.1 |
| `tests/test_ai_tools.py::test_fr_12_1_1_2_overview_keys` | FR-12.1.1.2 |
| `tests/test_ai_tools.py::test_fr_12_1_1_3_source_mock` | FR-12.1.1.3 |
| `tests/test_ai_tools.py::test_fr_12_1_2_1_users_shape` | FR-12.1.2.1 |
| `tests/test_ai_tools.py::test_fr_12_1_3_2_chatgpt_flag` | FR-12.1.3.2 |
| `tests/test_ai_tools.py::test_fr_12_1_5_1_high_spenders_sort` | FR-12.1.5.1 |
| `tests/test_ai_tools.py::test_fr_12_1_5_2_risk_classification` | FR-12.1.5.2 |
| `tests/test_ai_tools.py::test_fr_12_1_5_3_dollar_per_msg` | FR-12.1.5.3 |
| `tests/test_filters.py::test_fr_13_1_1_1_explicit_dates_priority` | FR-13.1.1.1 |
| `tests/test_filters.py::test_fr_13_1_1_2_date_range_explicit_or_computed` | FR-13.1.1.2 |
| `tests/test_filters.py::test_fr_13_1_2_2_today_yesterday_presets` | FR-13.1.2.2 |
| `tests/test_filters.py::test_fr_13_1_2_3_week_to_date` | FR-13.1.2.3 |
| `tests/test_filters.py::test_fr_13_1_2_4_month_to_date` | FR-13.1.2.4 |
| `tests/test_filters.py::test_fr_13_2_1_1_api_key_filter_in_costs` | FR-13.2.1.1 |
| `tests/test_filters.py::test_fr_13_3_1_2_project_filter_field` | FR-13.3.1.2 |
| `tests/test_sources_anthropic.py::test_fr_14_1_1_1_schema_required_keys` | FR-14.1.1.1 |
| `tests/test_sources_anthropic.py::test_fr_14_1_1_2_idempotent` | FR-14.1.1.2 |
| `tests/test_sources_anthropic.py::test_fr_14_1_1_3_latest_file_wins` | FR-14.1.1.3 |
| `tests/test_sources_anthropic.py::test_fr_14_1_1_4_filename_pattern` | FR-14.1.1.4 |
| `tests/test_sources_cursor.py::test_fr_14_1_2_1_shape` | FR-14.1.2.1 |
| `tests/test_sources_cursor.py::test_fr_14_1_2_2_json_over_csv_priority` | FR-14.1.2.2 |
| `tests/test_sources_anthropic.py::test_fr_14_3_1_1_json_wins_over_cursor_derived` | FR-14.3.1.1 |
| `tests/test_git_quality.py::test_classify_subject_tags_bug_fix_and_revert` | FR-15.1.1.1 |
| `tests/test_git_quality.py::test_load_commits_populates_git_commits_with_flags` | FR-15.1.1.2 |
| `tests/test_git_quality.py::test_get_team_quality_computes_rates` | FR-15.1.2.1 |
| `tests/test_git_quality.py::test_get_team_quality_human_vs_bot_split` | FR-15.1.2.2 |
| `tests/test_git_quality.py::test_get_team_quality_repo_filter` | FR-15.1.2.3 |
| `tests/test_git_quality.py::test_get_team_quality_date_filter` | FR-15.1.2.4 |
| `tests/test_git_quality.py::test_get_team_quality_empty_returns_safe_zeros` | FR-15.1.2.5 |
| `tests/test_git_quality.py::test_get_quality_per_author_dedupes_by_user_id` | FR-15.1.3.1 |
| `tests/test_git_quality.py::test_get_ai_spend_per_fix` | FR-15.1.4.1 |
| `tests/test_git_quality.py::test_get_ai_spend_per_fix_zero_fixes_safe` | FR-15.1.4.2 |
| `tests/test_git_quality.py::test_get_ai_spend_per_fix_repo_filter` | FR-15.1.4.3 |
| `tests/test_git_quality.py::test_get_high_churn_files` | FR-15.1.5.1 |
| `tests/test_git_quality.py::test_get_high_churn_files_repo_filter` | FR-15.1.5.2 |
| `tests/test_git_quality.py::test_get_high_churn_files_period_zero_means_all_time` | FR-15.1.5.3 |
| `tests/test_ux_help.py::test_section_renders_help_icon` | FR-16.1.1.1 |
| `tests/test_ux_help.py::test_kpi_row_renders_help_icon_per_card` | FR-16.1.1.2 |
| `tests/test_ux_help.py::test_help_icon_escapes_html` | FR-16.1.1.3 |
| `tests/test_ux_help.py::test_section_without_help_has_no_icon` | FR-16.1.1.4 |
| `tests/test_ux_help.py::test_help_icon_carries_aria_label` | FR-16.1.2.1 |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_1_1_default_fallback` | FR-17.1.1.1 (UC-17.1.1, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_1_2_default_repos_unchanged` | FR-17.1.1.2 (UC-17.1.1, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_1_3_priority_order` | FR-17.1.1.1 (UC-17.1.1, Service) |
| `tests/test_extract_git_stats.py::test_t_data_17_1_1_1_default_repos_format` | FR-17.1.1.2 (UC-17.1.1, Data) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_2_1_cli_parsing` | FR-17.1.2.1 (UC-17.1.2, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_2_2_cli_beats_env_and_file` | FR-17.1.2.2 (UC-17.1.2, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_2_3_empty_cli_falls_through` | FR-17.1.2.2 (UC-17.1.2, Service) |
| `tests/test_extract_git_stats.py::test_t_infra_17_1_3_1_env_var_visible` | FR-17.1.3.1 (UC-17.1.3, Infra) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_3_1_env_parsing` | FR-17.1.3.1 (UC-17.1.3, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_3_2_empty_env_falls_through` | FR-17.1.3.2 (UC-17.1.3, Service) |
| `tests/test_extract_git_stats.py::test_t_infra_17_1_4_1_config_file_exists` | FR-17.1.4.2 (UC-17.1.4, Infra) |
| `tests/test_extract_git_stats.py::test_t_infra_17_1_4_2_config_file_has_default_plus_engineering` | FR-17.1.4.2 (UC-17.1.4, Infra) |
| `tests/test_extract_git_stats.py::test_t_data_17_1_4_1_file_strips_comments_and_blanks` | FR-17.1.4.1 (UC-17.1.4, Data) |
| `tests/test_extract_git_stats.py::test_t_data_17_1_4_2_every_line_is_org_repo_format` | FR-17.1.4.1 (UC-17.1.4, Data) |
| `tests/test_extract_git_stats.py::test_t_svc_17_1_4_1_missing_or_empty_file_falls_back` | FR-17.1.4.2 (UC-17.1.4, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_2_1_1_ensure_repo_returns_none_on_failure` | FR-17.2.1.1 (UC-17.2.1, Service) |
| `tests/test_extract_git_stats.py::test_t_svc_17_2_1_2_main_continues_after_skip` | FR-17.2.1.2 (UC-17.2.1, Service) |
| `tests/test_extract_git_stats.py::test_t_data_17_2_2_1_short_name_after_slash` | FR-17.2.2.1 (UC-17.2.2, Data) |
| `tests/test_extract_git_stats.py::test_t_data_17_2_2_2_default_short_names_preserved` | FR-17.2.2.2 (UC-17.2.2, Data) |

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
