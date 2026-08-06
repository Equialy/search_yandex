
# SEO Competitor Analyzer & Writer

## 1. Общее описание проекта

[//]: # (**Название проекта:** Yandex SEO Competitor Analyzer & Article Generator  )

[//]: # (**Назначение:** Микросервис для поиска сайтов-конкурентов в Яндексе, асинхронного парсинга их структуры &#40;построение графов H1-H3 на NetworkX&#41;, извлечения главных смыслов через LLM, сохранения накапливаемого контекста диалога в БД и генерации экспертных SEO-статей через **KIE.AI &#40;GPT 5.2&#41;**.)

**Архитектурный стиль:** Clean Architecture (Чистая архитектура) + DDD (Domain-Driven Design) + Repository Pattern + Unit of Work (UOW) + IoC/DI (Dishka).

---

## 2. Технологический Стек

### Backend:
* **Язык и среда:** Python 3.14+ (Асинхронный `async/await` стек)
* **Веб-фреймворк:** FastAPI (`DishkaRoute`, `FromDishka`)
* **IoC/DI Контейнер:** Dishka (`make_async_container`, `Scope.APP`, `Scope.REQUEST`)
* **База данных:** PostgreSQL 17 / SQLite (`aiosqlite`)
* **ORM:** SQLAlchemy 2.0 (`AsyncSession`, `mapped_column`, `JSONB`, `UUIDv7`) + Alembic
* **HTTP Клиент & Парсинг:** `httpx.AsyncClient` (с `trust_env=False`), `BeautifulSoup4`, `NetworkX` (графы контента)
* **LLM Gateway:** KIE.AI API (модель `gpt-5-2`, метод `POST /gpt-5-2/v1/chat/completions`)
* **Search Gateway:** Yandex Search API v2 (`POST https://searchapi.api.cloud.yandex.net/v2/web/search`)
* **Валидация и DTO:** Pydantic v2 (`AliasGenerator`, `AliasChoices`, `to_camel`)

### Frontend:
* **Среда и сборка:** Node.js, Vite
* **Фреймворк:** React 19 + JavaScript
* **Менеджер состояния:** Redux Toolkit + RTK Query (`fetchBaseQuery`)
* **Стилизация:** Tailwind CSS v4

---

## 3. Дерево Папок Проекта

```text
competitor_analyzer/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── competitors/
│   │   │           ├── schemas.py       # DTO Схемы Pydantic v2 (camelCase/snake_case)
│   │   │           └── routers.py       # Эндпоинты FastAPI (DishkaRoute)
│   │   ├── application/
│   │   │   ├── ioc/                     # Модульные провайдеры Dishka
│   │   │   │   ├── infrastructure.py    # Engine, Session, HTTP Client, UOW
│   │   │   │   └── competitors.py       # Gateways и Use Cases
│   │   │   ├── services/
│   │   │   │   └── competitors/
│   │   │   │       └── repositories.py  # Репозитории (Project, Competitor, Article)
│   │   │   ├── use_cases/               # Бизнес-сценарии
│   │   │   │   ├── analyze_competitors.py
│   │   │   │   └── generate_article.py
│   │   │   └── uow.py                   # Unit of Work (Интерфейс и Реализация)
│   │   ├── infrastructure/
│   │   │   ├── database/
│   │   │   │   ├── models/
│   │   │   │   │   └── competitors.py   # SQLAlchemy 2.0 Модели
│   │   │   │   ├── base_repository.py   # Generic BaseRepository[T]
│   │   │   │   └── engine.py            # Async Engine & SessionMaker
│   │   │   └── gateways/
│   │   │       ├── yandex_search.py     # Yandex Search API v2
│   │   │       ├── site_parser.py       # Scraper + NetworkX Graph Builder
│   │   │       └── kie_api.py           # KIE.AI GPT 5.2 Gateway
│   │   ├── config/
│   │   │   └── settings.py              # Pydantic BaseSettings (.env)
│   │   └── main.py                      # Точка входа FastAPI + Dishka Setup
│   ├── alembic/                         # Миграции базы данных
│   ├── .env
│   └── requirements.txt
│
└── frontend/
    ├── src/
    │   ├── components/                  # Пошаговые компоненты
    │   │   ├── Step1Analyze.jsx         # Форма ввода ключа Яндекса
    │   │   ├── Step2Generate.jsx        # Настройка ТЗ статьи
    │   │   └── Step3ArticleView.jsx     # Просмотр статьи + Чат в контексте
    │   ├── store/                       # Redux Toolkit
    │   │   ├── competitorApi.js         # RTK Query API
    │   │   ├── projectSlice.js          # Slices состояния
    │   │   └── index.js                 # Redux Store Config
    │   ├── App.jsx                      # Главный Layout
    │   ├── index.css                    # Tailwind CSS v4
    │   └── main.jsx                     # Provider Store Setup
    ├── package.json
    └── vite.config.js
```

---

## 4. Спецификация Базовых Компонентов (Backend)
### 4.1. Настройки (`src/config/settings.py` & `src/config/database.py`)
Используются вложенные Pydantic-модели с поддержкой двойного подчеркивания `__` в `.env`:
* `settings.db`: `DatabaseConfig` (содержит `pg: PostgresConfig` и `sqla: SQLAlchemyConfig`). URL генерируется через `settings.db.async_url`.
* `settings.kie`: `KIEConfig` (содержит `settings.kie.API_KEY` и `settings.kie.KIE_BASE_URL`).
* `settings.OPENAI`: `OpenAI` (содержит `settings.OPENAI.API_KEY` и `settings.OPENAI.MODEL`).
* `settings.YANDEX_API_KEY` и `settings.YANDEX_FOLDER_ID`: верхний уровень настроек.

### Инициализация Engine БД:
Выполняется вызовом `new_engine(settings.db)` из `src/infrastructure/database/engine.py`.
### 4.2. База Данных и Модели (`src/infrastructure/database/models/competitors.py`)
* Использование `UUIDv7` для первичных ключей.
* `JSONB` поле `chat_history` в таблице `projects` хранит накапливаемый контекст диалога с нейросетью: `[{"role": "system", "content": "..."}, ...]`.
* `created_at` всегда задается с `default=lambda: datetime.now(timezone.utc)` и `server_default=func.now()`.

### 4.3. Базовый Репозиторий (`src/infrastructure/database/base_repository.py`)
* Метод `add(data: Union[T, dict])` умеет принимать как готовые экземпляры моделей ORM `T`, так и словари `dict`.
* Обязателен вызов `await self.session.refresh(obj)` после `flush()`, чтобы мгновенно подгружать серверные дефолты (`created_at`).

### 4.4. Unit of Work (`src/application/uow.py`)
* Содержит свойства `projects`, `competitors`, `articles`.
* Управляет границами единой атомарной транзакции (`async with uow:`). Никаких `commit()` внутри сервисов/репозиториев!

### 4.5. Шлюзы (Gateways)
1. **`YandexSearchGateway` (`src/infrastructure/gateways/yandex_search.py`)**:
   * Делает `POST` запрос к Yandex Search API v2: `https://searchapi.api.cloud.yandex.net/v2/web/search`.
   * Передает заголовок `Authorization: Api-Key <KEY>`.
   * Распаковывает Base64 из поля `rawData` в XML и извлекает ссылки сайтов (`<doc><url>`).
   * Содержит фолбек-ссылки (Википедия) на случай сбоев сети.

2. **`SiteParserGateway` (`src/infrastructure/gateways/site_parser.py`)**:
   * Скачивает HTML через `httpx.AsyncClient` с реальными браузерными `User-Agent`.
   * Находит заголовки `H1`, `H2`, `H3` и строит графовую иерархию связей с помощью **`networkx.DiGraph`**.
   * Если заголовки H1-H3 отсутствуют (как у SPA/маркетплейсов WB, DNS), формирует синтетическую иерархию графа из `Title` и `Meta Description`.

3. **`KieApiGateway` (`src/infrastructure/gateways/kie_api.py`)**:
   * Запросы к `POST https://api.kie.ai/gpt-5-2/v1/chat/completions`.
   * Форматирует массив сообщений под требования KIE.AI: `content` передается массивом объектов `[{"type": "text", "text": "..."}]`.
   * Управляет параметром `"reasoning_effort": "high"`.

---

## 5. Внедрение Зависимостей (Dishka IoC)

Провайдеры разделены на 2 уровня:

1. **`InfrastructureProvider` (`src/application/ioc/infrastructure.py`)**:
   * `AsyncEngine`, `AsyncSession` (с `AsyncGenerator[T, None]`).
   * `httpx.AsyncClient` с `trust_env=False` (чтобы игнорировать некорректные прокси Windows).
   * `uow = provide(UnitOfWork, scope=Scope.REQUEST, provides=UnitOfWorkProtocol)`.

2. **`CompetitorsProvider` (`src/application/ioc/competitors.py`)**:
   * Декларативное объявление через атрибуты класса:
     * `yandex_gateway = provide(YandexSearchGateway, scope=Scope.APP)`
     * `parser_gateway = provide(SiteParserGateway, scope=Scope.APP)`
     * `kie_gateway = provide(KieApiGateway, scope=Scope.APP)`
     * `analyze_competitors_use_case = provide(AnalyzeCompetitorsUseCase, scope=Scope.REQUEST)`
     * `generate_article_use_case = provide(GenerateArticleUseCase, scope=Scope.REQUEST)`

---

## 6. Правила Pydantic Схем (`src/api/v1/competitors/schemas.py`)

Для корректной работы с SQLAlchemy ORM и отдачи `camelCase` на фронтенд используется `AliasGenerator`:

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
* **Все поля моделей в Python объявляются строго в `snake_case`** (`project_id`, `created_at`, `found_urls`).
* Pydantic автоматически читает их из ORM и переводит в `camelCase` (`projectId`, `createdAt`, `foundUrls`) при сериализации в JSON.

---

## 7. Спецификация Frontend (React + Redux Toolkit)

### Redux RTK Query (`src/store/competitorApi.js`):
* `analyzeCompetitors` $\rightarrow$ `POST /v1/competitors/analyze` (`{ keyword, limit }`).
* `generateArticle` $\rightarrow$ `POST /v1/competitors/projects/{projectId}/generate-article` (`{ topic, instructions }`).
* `sendContextChat` $\rightarrow$ `POST /v1/competitors/projects/{projectId}/chat` (`{ prompt }`).

### Пошаговый Пользовательский Сценарий (UI Flow):
1. **Шаг 1 (Step1Analyze):** Ввод ключевого слова $\rightarrow$ Показывает loader парсинга Яндекса $\rightarrow$ Сохраняет `projectId` и найденные ссылки в Redux $\rightarrow$ Переключает на Шаг 2.
2. **Шаг 2 (Step2Generate):** Показывает список проанализированных сайтов $\rightarrow$ Позволяет задать тему и ТЗ $\rightarrow$ Отправляет запрос к KIE.AI GPT 5.2 $\rightarrow$ Сохраняет статью в Redux $\rightarrow$ Переключает на Шаг 3.
3. **Шаг 3 (Step3ArticleView):** Выводит готовую статью в формате документа $\rightarrow$ Внизу располагает чат-формат для продолжения доработки этой статьи в сохраненном контексте сессии.

---

## 8. Инструкция по Запуску и Развертыванию

### Бэкенд:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # или .venv\Scripts\activate на Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn src.main:app --reload --port 8000
```

### Фронтенд:
```bash
cd frontend
pnpm install  # или npm install
pnpm dev      # Запуск на http://localhost:5173
```