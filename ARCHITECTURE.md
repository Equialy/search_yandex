
# SEO Competitor Analyzer & Writer

## 1. Общее описание проекта

**Назначение:** платформа для поиска сайтов-конкурентов в Яндексе, асинхронного парсинга их структуры (граф H1–H3 на NetworkX), LSA/коммерческого анализа через LLM, накопления контекста проекта в БД, генерации SEO-статей и работы с ними через веб-UI, REST API, SEO-агента и MCP (Cursor / Claude Desktop / браузер).

**Архитектурный стиль:** Clean Architecture + DDD + Repository Pattern + Unit of Work (UOW) + IoC/DI (Dishka).

**Репозитории:**
* Backend: `search_yandex/` (Python, FastAPI)
* Frontend: `search_yandex_frontend/` (React, отдельный проект)

---

## 2. Технологический стек

### Backend
* **Язык:** Python 3.14+ (`async/await`)
* **Менеджер зависимостей:** `uv` + `pyproject.toml`
* **Веб-фреймворк:** FastAPI (`DishkaRoute`, `FromDishka`)
* **IoC/DI:** Dishka (`make_async_container`, `Scope.APP`, `Scope.REQUEST`)
* **БД:** PostgreSQL (`asyncpg`) + Alembic
* **ORM:** SQLAlchemy 2.0 (`AsyncSession`, `JSONB`, `UUIDv7`)
* **HTTP & парсинг:** `httpx`, `curl-cffi`, `BeautifulSoup4`, `NetworkX`
* **LLM:** OpenAI API (`OpenAiGateway`, основной путь) + KIE.AI (`KieApiGateway`, legacy)
* **MCP:** FastMCP 2.x (`Streamable HTTP`, mount на `/mcp`)
* **DTO:** Pydantic v2 (`AliasGenerator`, camelCase ↔ snake_case)

### Frontend
* **Сборка:** Vite 8
* **UI:** React 19 + JavaScript
* **Роутинг:** React Router v7
* **Состояние:** Redux Toolkit + RTK Query
* **MCP-клиент:** `@modelcontextprotocol/sdk` (`StreamableHTTPClientTransport`)
* **Стили:** Tailwind CSS v4
* **Markdown:** `react-markdown` + `remark-gfm`

---

## 3. Дерево папок проекта

```text
search_yandex/                          # Backend
├── src/
│   ├── api/v1/
│   │   ├── competitors/
│   │   │   ├── schemas.py              # DTO проектов, конкурентов, статей
│   │   │   └── routers.py              # CRUD проектов, анализ, генерация, чат
│   │   ├── agent/
│   │   │   ├── schemas.py              # DTO чата SEO-агента
│   │   │   └── routers.py              # POST /v1/agent/chat (SSE)
│   │   └── text_router/
│   │       ├── schema.py
│   │       ├── service.py              # Детектор AI / очеловечивание
│   │       └── routers.py
│   ├── application/
│   │   ├── ioc/
│   │   │   ├── infrastructure.py       # Engine, Session, OpenAI, UOW
│   │   │   ├── gateways.py             # Yandex, Parser, KIE, OpenAI gateways
│   │   │   └── competitors.py          # Use Cases + TextAiService
│   │   ├── mcp/
│   │   │   ├── server.py               # FastMCP tools + http_app
│   │   │   ├── auth.py                 # JWT / test_mcp_key (IS_LOCAL)
│   │   │   ├── helpers.py              # Прокси tool → internal REST
│   │   │   ├── proxy.py                # ASGITransport → FastAPI
│   │   │   └── router.py               # GET /api-keys/mcp/connect
│   │   ├── services/competitors/
│   │   │   └── repositories.py       # Project, Competitor, Article repos
│   │   ├── use_cases/
│   │   │   ├── analyze_competitors.py  # Анализ + экспорт в .txt
│   │   │   ├── generate_article.py
│   │   │   ├── chat_context.py
│   │   │   ├── list_projects.py
│   │   │   ├── get_project.py
│   │   │   └── agent_chat.py           # LLM function calling + SSE
│   │   ├── prompts.py
│   │   └── uow.py
│   ├── infrastructure/
│   │   ├── database/
│   │   │   ├── models/competitors.py
│   │   │   ├── base_repository.py
│   │   │   ├── engine.py
│   │   │   └── migrations/
│   │   └── gateways/
│   │       ├── yandex_search.py
│   │       ├── site_parser.py
│   │       ├── openai_gateway.py
│   │       ├── kie_api.py
│   │       └── llm_gateway.py
│   ├── config/
│   │   ├── settings.py
│   │   └── database.py
│   ├── bootstrap.py                    # lifespan, apply_routes, mount /mcp
│   ├── main.py
│   └── middlewares.py                  # CORS + expose mcp-session-id
├── exports/analysis/                   # JSON в .txt после анализа (gitignore)
├── alembic.ini
├── pyproject.toml
└── docker-compose.yml

search_yandex_frontend/                 # Frontend (отдельный репозиторий/папка)
├── src/
│   ├── components/
│   │   ├── Layout.jsx                  # Sidebar + Outlet
│   │   ├── Step1Analyze.jsx
│   │   ├── Step2Generate.jsx
│   │   ├── Step3ArticleView.jsx
│   │   ├── AgentChat.jsx               # SEO-агент (SSE через RTK)
│   │   ├── McpAgentChat.jsx            # Ручной вызов MCP tools
│   │   └── TextHumanizer.jsx
│   ├── pages/
│   │   ├── GeneratorPage.jsx           # Мастер 3 шага
│   │   ├── ProjectsPage.jsx            # Список проектов
│   │   └── ProjectDetailPage.jsx       # Конкуренты + статьи
│   ├── store/
│   │   ├── competitorApi.js            # RTK Query (REST + agentChat SSE)
│   │   ├── projectSlice.js
│   │   └── index.js
│   ├── App.jsx                         # React Router
│   └── main.jsx
└── package.json
```

---

## 4. Backend: ключевые компоненты

### 4.1. Настройки (`src/config/settings.py`)

Вложенные Pydantic-модели, env через `__`:
* `settings.db` — PostgreSQL
* `settings.OPENAI` — `API_KEY`, `MODEL` (основной LLM)
* `settings.kie` — KIE.AI (legacy)
* `settings.jwt` — секрет для MCP JWT
* `settings.YANDEX_API_KEY`, `settings.YANDEX_FOLDER_ID`
* `settings.IS_LOCAL` — dev-режим (`test_mcp_key` для MCP)
* `settings.base_url`, `settings.cors_origins`

### 4.2. Модели БД (`competitor_data`, `projects`, `articles`)

| Таблица | Назначение |
|---------|------------|
| `projects` | Сессия анализа, `keyword`, `chat_history` (JSONB) |
| `competitor_data` | URL, `title`, `graph_data` (title/description/body_text), `summary` |
| `articles` | `title`, `content`, `reasoning` |

`graph_data` — SEO-метаданные страницы конкурента (title, description, body_text). На фронте отображаются в разделе «Проекты».

### 4.3. Unit of Work (`src/application/uow.py`)

Свойства: `projects`, `competitors`, `articles`.  
Транзакции только через `async with uow:` — без `commit()` в репозиториях.

### 4.4. Use Cases

| Use Case | Описание |
|----------|----------|
| `AnalyzeCompetitorsUseCase` | Yandex → parse → LSA summary → БД + экспорт `exports/analysis/*.txt` |
| `GenerateArticleUseCase` | Статья по контексту проекта (OpenAI) |
| `ContinueContextChatUseCase` | Доработка статьи в чате |
| `ListProjectsUseCase` | Список проектов с counts |
| `GetProjectUseCase` | Проект + competitors + articles |
| `AgentChatUseCase` | OpenAI function calling, инструменты как у MCP + `get_project_results` |

### 4.5. Экспорт анализа в файл

После каждого успешного анализа `AnalyzeCompetitorsUseCase` вызывает `save_analysis_to_txt()`:
* Путь: `exports/analysis/analysis_{YYYY-MM-DD_HH-MM-SS}_{project_id}.txt`
* Формат: JSON (projectId, keyword, competitors с seoMeta/summary)

### 4.6. Gateways

1. **`YandexSearchGateway`** — Yandex Search API v2, возвращает `{url, title, description}`.
2. **`SiteParserGateway`** — HTML → NetworkX граф H1–H3, fallback title/description из Яндекса, фильтр маркетплейсов.
3. **`OpenAiGateway`** — основной LLM (`chat.completions`, summarize, history).
4. **`KieApiGateway`** — legacy KIE GPT 5.2.

---

## 5. REST API

Базовый URL: `http://localhost:8000/v1`  
Авторизация REST: **нет** (JWT только для MCP).

### Competitors (`/v1/competitors`)

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/analyze` | Анализ конкурентов (keyword/url, limit, projectId?) |
| GET | `/projects` | Список проектов |
| GET | `/projects/{id}` | Детали: competitors + articles |
| POST | `/projects/{id}/generate-article` | Генерация статьи |
| POST | `/projects/{id}/chat` | Чат в контексте проекта |

### Agent (`/v1/agent`)

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/chat` | SEO-агент, **SSE** (`event: status/delta/message/error/done`) |

### Text (`/v1/text`)

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/detect` | Детектор AI-текста |
| POST | `/humanize` | Очеловечивание текста |

### MCP Connect

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api-keys/mcp/connect` | Инструкция подключения MCP-клиента |

---

## 6. MCP (Model Context Protocol)

### Сервер
* **Mount:** `app.mount("/mcp", mcp_http_app)` в `bootstrap.py`
* **Транспорт:** Streamable HTTP (не legacy SSE)
* **Auth:** `Authorization: Bearer <JWT>` или `test_mcp_key` при `IS_LOCAL=true`
* **CORS:** `expose_headers: mcp-session-id, mcp-protocol-version`

### Tools
* `analyze_competitors`
* `generate_seo_article`
* `continue_chat_refinement`

Tools проксируют вызовы во внутренние REST-роуты через `ASGITransport` (`proxy.py`).

### Клиенты
* **Cursor / Claude:** конфиг из `/api-keys/mcp/connect`
* **Браузер (McpAgentChat):** `@modelcontextprotocol/sdk` + `StreamableHTTPClientTransport`

---

## 7. SEO Agent (веб-чат)

`AgentChatUseCase` — OpenAI с function calling:
* `get_project_results` — чтение сохранённых данных (без перегенерации)
* `analyze_competitors`, `generate_seo_article`, `continue_chat_refinement`

Поток: `POST /v1/agent/chat` → `StreamingResponse` (SSE) → фронт через RTK Query `agentChat` mutation (`queryFn` + `fetch` для stream body).

---

## 8. Dishka IoC

```text
make_async_container(
    InfrastructureProvider(),   # Engine, Session, httpx, OpenAI, UOW
    GatewaysProvider(),         # Yandex, Parser, KIE, OpenAI gateways
    CompetitorsProvider(),      # Use cases, TextAiService
    FastapiProvider(),
)
```

Роутеры используют `route_class=DishkaRoute` и `FromDishka[UseCase]`.

---

## 9. Frontend

### Роутинг (`App.jsx`)

| Путь | Страница |
|------|----------|
| `/` | GeneratorPage (мастер 3 шага) |
| `/projects` | Список проектов |
| `/projects/:projectId` | Конкуренты (title/description из graphData) + статьи |
| `/agent` | SEO Agent Chat |
| `/humanizer` | Детектор / очеловечивание |
| `/mcp` | Панель ручного вызова MCP tools |

### RTK Query (`competitorApi.js`)

| Hook | Endpoint |
|------|----------|
| `useAnalyzeCompetitorsMutation` | POST `/competitors/analyze` |
| `useGetProjectsQuery` | GET `/competitors/projects` |
| `useGetProjectQuery` | GET `/competitors/projects/{id}` |
| `useGenerateArticleMutation` | POST `.../generate-article` |
| `useSendContextChatMutation` | POST `.../chat` |
| `useAgentChatMutation` | POST `/agent/chat` (SSE, `onEvent` callback) |
| `useDetectAiTextMutation` | POST `/text/detect` |
| `useHumanizeTextMutation` | POST `/text/humanize` |

Base URL: `http://localhost:8000/v1` (hardcoded).

### UI Flow

1. **Мастер (Generator):** Step1 анализ → Step2 генерация → Step3 статья + контекстный чат.
2. **Проекты:** просмотр всех сохранённых анализов и статей (источник истины — БД).
3. **SEO Agent:** естественный язык → LLM выбирает инструменты → ответ в чате.
4. **MCP Tools:** ручной выбор tool и аргументов (для отладки).

---

## 10. Pydantic DTO

`BaseDTO` с `AliasGenerator` — Python `snake_case`, JSON `camelCase`:

```python
class BaseDTO(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda field_name: AliasChoices(field_name, to_camel(field_name)),
            serialization_alias=to_camel,
        ),
    )
```

---

## 11. Запуск

### Backend
```bash
cd search_yandex
uv sync
alembic upgrade head
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: `http://localhost:8000/docs`

### Frontend
```bash
cd search_yandex_frontend
npm install
npm run dev    # http://localhost:5173
```

### Docker (опционально)
```bash
docker-compose up -d   # PostgreSQL, RabbitMQ и др.
```

---

## 12. Диаграмма потоков

```text
┌─────────────┐     REST/SSE      ┌──────────────────┐
│  React UI   │ ────────────────► │  FastAPI :8000   │
│  (RTK Query)│                   │  /v1/competitors │
└─────────────┘                   │  /v1/agent       │
       │                          │  /v1/text        │
       │ MCP (browser)            └────────┬─────────┘
       └──────────────────────────► /mcp ◄─┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              Use Cases            OpenAI API           PostgreSQL
                    │                                        │
                    └──────────► exports/analysis/*.txt ◄───┘
```

```text
Cursor / Claude ──► /mcp/ (Streamable HTTP + Bearer)
                         │
                         └──► MCP tools ──► internal REST (ASGI proxy)
```
