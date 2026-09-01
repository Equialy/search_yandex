from unittest.mock import AsyncMock, patch

import httpx
from bs4 import BeautifulSoup
import pytest


from src.infrastructure.gateways.site_parser import (
    SiteParserGateway,
    _is_beget_challenge,
    _prepare_content_root,
)



def test_is_beget_challenge(beget_challenge_html, sample_landing_html):
    """Проверка определения антибот-заглушки Beget."""
    assert _is_beget_challenge(beget_challenge_html) is True
    assert _is_beget_challenge(sample_landing_html) is False
    assert _is_beget_challenge("") is False


def test_prepare_content_root_strips_noise():
    """Проверка, что навигация, cookie и формы вырезаются, а main остается."""
    raw_html = """
    <html>
        <body>
            <header>Шапка сайта</header>
            <div class="cookie-banner">Куки-баннер</div>
            <main>
                <h1>Заголовок внутри Main</h1>
                <p>Основной смысловой текст страницы.</p>
            </main>
            <footer class="site-footer">Подвал</footer>
        </body>
    </html>
    """
    soup = BeautifulSoup(raw_html, 'html.parser')
    content_root = _prepare_content_root(soup)
    text = content_root.get_text(' ', strip=True)

    assert 'Заголовок внутри Main' in text
    assert 'Основной смысловой текст' in text
    assert 'Шапка сайта' not in text
    assert 'Куки-баннер' not in text
    assert 'Подвал' not in text



# -------------------------------------------------------------
# ТЕСТЫ ПАРСИНГА САЙТА (parse_site_to_graph)
# -------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_parse_site():
    target_url = "https://knopka.com/"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        parser = SiteParserGateway(http_client=client)
        result = await parser.parse_site_to_graph(url=target_url)

    print(result["url"])
    print(f" РЕЗУЛЬТАТ ПАРСИНГА ДЛЯ: {result['url']}")
    print("=" * 60)
    print(f" TITLE:\n{result['title']}\n")
    print(f" DESCRIPTION:\n{result['description']}\n")
    print(f" LOGO URL:\n{result['logo_url']}\n")

    print("СТРУКТУРА ЗАГОЛОВКОВ (H1–H4):")
    for h in result["content_structure"]["headings"]:
        print(f"   [{h['level']}] {h['text']}")

    print(f"\nНАЙДЕНО ТАБЛИЦ В MARKDOWN: {len(result['content_structure']['tables'])}")
    for idx, tbl in enumerate(result["content_structure"]["tables"], 1):
        print(f"\n--- Таблица #{idx} ---\n{tbl}")

    print(f"\nFAQ БЛОКИ: {len(result['content_structure']['faq_blocks'])}")

    print(f"\nЧИСТЫЙ ТЕКСТ :\n{result['clean_text']}...")
    print("=" * 60)

    # 5. Автоматические проверки (Assertions)
    assert result["is_blocked"] is False, "Сайт заблокировал запрос или упал с ошибкой"
    assert len(result["title"]) > 5, "Заголовок страницы (title) не должен быть пустым"
    assert len(result["content_structure"]["headings"]) > 0, "Должен быть найден хотя бы один заголовок"
    assert len(result["clean_text"]) > 200, "Текст страницы не извлекся или слишком короткий"

