import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm.attributes import flag_modified

from src.application.prompts import SEO_GUIDELINE_TEXT
from src.application.uow import UnitOfWorkProtocol
from src.config.settings import BASE_DIR
from src.infrastructure.database.models.competitors import Article
from src.infrastructure.gateways.openai_gateway import OpenAiGateway
from src.infrastructure.gateways.site_parser import SiteParserGateway

EXPORTS_ARTICLES_DIR = BASE_DIR / "exports" / "articles"
EXPORTS_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def save_article_to_txt(article: Article) -> Path:
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    data = {
        "id": str(article.id),
        "projectId": str(article.project_id),
        "title": article.title,
        "content": article.content,
        "reasoning": article.reasoning,
        "createdAt": article.created_at.isoformat() if article.created_at else datetime.now(timezone.utc).isoformat(),
    }

    file_path = EXPORTS_ARTICLES_DIR / f"article_{now_str}_{article.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return file_path


class GenerateArticleUseCase:
    def __init__(
            self,
            uow: UnitOfWorkProtocol,
            ai_gateway: OpenAiGateway,
            parser_gateway: SiteParserGateway
    ):
        self._uow = uow
        self._kie = ai_gateway
        self._parser = parser_gateway

    async def execute(
            self,
            project_id: uuid.UUID,
            topic: str,
            instructions: str = "",
            target_site: str = ""
    ) -> Article:
        async with self._uow as uow:
            project = await uow.projects.get_with_relations(project_id)
            if not project:
                raise ValueError("Проект не найден")

            company_name = target_site if target_site else "Наша компания"
            target_data_prompt = ""

            if target_site and (target_site.startswith("http://") or target_site.startswith("https://")):
                print(f"[GenerateArticleUseCase]: Скачиваем реальные прайсы вашего сайта {target_site}...")
                parsed_target = await self._parser.parse_site_to_graph(target_site)

                if parsed_target and parsed_target.get("body_text"):
                    company_name = parsed_target.get("title") or target_site
                    target_data_prompt = f"""
                    РЕАЛЬНЫЕ ДАННЫЕ И ПРАЙСЫ НАШЕГО САЙТА ({target_site}):
                    Title нашего сайта: {parsed_target.get('title')}
                    Description нашего сайта: {parsed_target.get('description')}
                    Настоящие тексты и цены с нашего сайта:
                    {parsed_target.get('body_text')}
                    """

            prompt = f"""Напиши коммерческую SEO-статью / страницу услуги на тему '{topic}' СПЕЦИАЛЬНО ДЛЯ НАШЕЙ КОМПАНИИ: '{company_name}'.
                    
                                       
                    СТРОГИЕ ПРАВИЛА ЧЕЛОВЕЧНОСТИ И СТИЛЯ:
                    1. ЗАПРЕЩЕНО использовать технические названия блоков в заголовках (НЕ пиши 'Вводный блок', 'Описание услуги', 'Наши преимущества', 'Кейсы и гарантии', 'Финальный абзац'). Заголовки H2/H3 должны звучать естественного для человека (например: 'Этапы работы', 'Риски и штрафы', 'Почему выгодно работать с нами').
                    2. НИКАКОГО МЕХАНИЧЕСКОГО ПЕРЕСПАМА: не вставляй дословно длинную фразу '{topic} {company_name}' в каждый заголовок и таблицу. Склоняй слова и вписывай их органично в предложения.
                    3. ЭКСПЕРТНОСТЬ И БОЛИ КЛИЕНТА: Избегай пустой воды ('индивидуальный подход', 'высокое качество'). Пиши про реальные финансовые/юридические риски клиента, конкретные законы, штрафы и процессы.
                    4. ТАБЛИЦЫ: Колонки таблицы должны иметь короткие названия ('Критерий | Конкуренты | {company_name}').
                    
                    ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СТАТЬИ ПО МЕТОДИЧКЕ:
                    1. TITLE И DESCRIPTION:
                       - Title (до 70 симв.): главный ключ + '{company_name}' + выгода.
                       - Description (150-160 симв.): главный ключ + '{company_name}' + условия/цена.
                    
                    2. H1: Единый главный заголовок страницы с главным ключом.
                    
                    3. ВВОДНЫЙ РАЗДЕЛ (Первый абзац содержит главный ключ и имя компании).
                    
                    4. СРАВНЕНИЕ С КОНКУРЕНТАМИ РЫНКА (Таблица + разбор слабых мест рынка).
                    
                    5. НАШИ ПРЕИМУЩЕСТВА (Конкретные факты и цифры).
                    
                    6. ЭТАПЫ РАБОТ И ФАКТОРЫ СТОИМОСТИ (Таблица цен).
                    
                    7. ДОКАЗАТЕЛЬСТВА И ГАРАНТИИ (Отзывы, риски, гарантии договора).
                    
                    8. ЗАКЛЮЧЕНИЕ (Последний абзац содержит главный ключ и имя компании).   
                    
                    {target_data_prompt}
                    
                                                      
                    СТРОГИЕ ПРАВИЛА ВЕРСТКИ И МЕТОДИЧКИ:
                    {SEO_GUIDELINE_TEXT}
                    
                    ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ:
                    {instructions}
                    """

            content, reasoning, updated_history = await self._kie.completion_with_history(
                history=list(project.chat_history),
                user_prompt=prompt
            )

            project.chat_history = updated_history
            flag_modified(project, "chat_history")

            article = Article(
                project_id=project.id,
                title=topic,
                content=content,
                reasoning=reasoning
            )
            await uow.articles.add(article)

            saved_article_file = save_article_to_txt(article)
            print(f"[Article Saved to File]: {saved_article_file}")

            return article