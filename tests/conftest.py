import asyncio
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def sample_landing_html() -> str:
    """Реалистичный пример HTML-страницы коммерческого сайта."""
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Создание сайтов-визиток под ключ в Москве | ПроПремиум</title>
        <meta name="description" content="Разработка продающих сайтов-визиток от 15 000 руб. Срок от 3 дней.">
        <meta property="og:title" content="Сайты-визитки в Москве">
        <link rel="icon" href="https://example.com/logo.png">
    </head>
    <body>
        <header class="site-header">
            <div class="logo"><img src="/images/header-logo.png" alt="Logo"></div>
            <nav class="navbar">
                <a href="/about">О нас</a>
                <a href="/services">Услуги</a>
            </nav>
            <div class="top-contacts">+7 (499) 000-00-00</div>
        </header>

        <div class="cookie-modal" id="cookie-popup">
            Мы используем cookie <button>Согласен</button>
        </div>

        <main>
            <h1>Разработка сайтов-визиток для бизнеса</h1>
            <p>Качественный сайт-визитка позволяет быстро презентовать компанию в интернете и привлекать новых клиентов.</p>

            <h2>Тарифы и стоимость разработки</h2>
            <table>
                <thead>
                    <tr><th>Пакет</th><th>Срок</th><th>Цена</th></tr>
                </thead>
                <tbody>
                    <tr><td>Стандарт</td><td>3 дня</td><td>15 000 ₽</td></tr>
                    <tr><td>Бизнес</td><td>7 дней</td><td>35 000 ₽</td></tr>
                </tbody>
            </table>

            <h2>Часто задаваемые вопросы</h2>
            <div class="faq-accordion">
                <div class="question">Что входит в стоимость?</div>
                <div class="answer">В стоимость входит адаптивный дизайн, наполнение и базовая SEO-оптимизация.</div>
            </div>

            <!-- Мусорные кнопки и тексты, которые парсер обязан отфильтровать -->
            <button>Оставить заявку</button>
            <p>Подробнее</p>
            <p>+7 (999) 111-22-33</p>
        </main>

        <footer class="footer">
            <p>© 2026 ПроПремиум. Все права защищены. <a href="/policy">Политика конфиденциальности</a></p>
        </footer>
    </body>
    </html>
    """


@pytest.fixture
def beget_challenge_html() -> str:
    """Пример антибот-заглушки Beget."""
    return "<html><head><script>set_cookie(); location.reload(); beget=begetok;</script></head></html>"