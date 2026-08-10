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
                    
                    {target_data_prompt}
                    
                    СТРОГОЕ ПРАВИЛО ПО ЦЕНАМ И ПРАЙСАМ:
                    - Цены в блоке 'Факторы стоимости / Таблица цен' бери СТРОГО из спарсенного текста НАШЕГО сайта выше! 
                    - Если в тексте нашего сайта указаны цены (например, сайт-визитка от 40 000 руб., каталог от 60 000 руб., интернет-магазин от 80 000 руб., корпоративный сайт от 180 000 руб.), указывай СТРОГО ЭТИ ЦЕНЫ! НЕ ВЫДУМЫВАЙ чужие цены и не бери дешёвые цены конкурентов!
                    
                    ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СТАТЬИ ПО МЕТОДИЧКЕ:
                    1. TITLE И DESCRIPTION:
                       - Title (до 70 симв.): главный ключ + '{company_name}' + выгода.
                       - Description (150-160 симв.): главный ключ + '{company_name}' + условия/цена.
                    
                    2. H1: Единый главный заголовок страницы с главным ключом.
                    
                    3. ВВОДНЫЙ БЛОК И ОПИСАНИЕ УСЛУГИ:
                       - Первый абзац обязательно содержит главный ключ и название компании '{company_name}'.
                    
                    4. ОБЯЗАТЕЛЬНЫЙ РАЗДЕЛ: "АНАЛИЗ И СРАВНЕНИЕ С КОНКУРЕНТАМИ РЫНКА":
                       - Проведи прямой разбор сильных и слабых сторон конкурентов на рынке по данному запросу.
                       - Укажи минус и слабые места большинства конкурентов (скрытые наценки, затянутые сроки, отсутствие гарантий).
                       - Покажи, как компания '{company_name}' устраняет эти слабые стороны.
                       - Построй Markdown-ТАБЛИЦУ сравнения: "Критерий | Конкуренты на рынке | Наша компания ({company_name})".
                    
                    5. НАШИ ПРЕИМУЩЕСТВА И ПОЗИЦИОНИРОВАНИЕ:
                       - Маркированный список преимуществ с конкретными фактами и цифрами.
                    
                    6. ЭТАПЫ РАБОТ И ФАКТОРЫ СТОИМОСТИ:
                       - Четкие шаги оказания услуги и таблица цен/пакетов НАШЕЙ компании.
                    
                    7. КЕЙСЫ, ДОКАЗАТЕЛЬСТВА И ГАРАНТИИ:
                       - Конкретные результаты, цифры и официальные гарантии договора.
                    
                    8. ФИНАЛЬНЫЙ АБЗАЦ:
                       - Последний абзац обязательно содержит главный ключ и название компании '{company_name}'.
                    
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