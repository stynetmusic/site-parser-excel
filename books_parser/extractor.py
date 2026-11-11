"""Извлечение строк из HTML. Преобразование типов делает модуль normalizer."""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from books_parser.models import BookPageDetails, RawBook


def extract_catalog_books(html: str, page_url: str) -> list[RawBook]:
    """Читает карточки книг с одной страницы каталога."""

    soup = BeautifulSoup(html, "html.parser")
    return [_extract_card(article, page_url) for article in soup.select("article.product_pod")]


def extract_next_page_url(html: str, page_url: str) -> str | None:
    """Возвращает абсолютный адрес следующей страницы каталога.

    На первой странице ссылка выглядит как catalogue/page-2.html, а на
    следующих — как page-3.html. urljoin собирает правильный адрес из
    адреса текущей страницы и относительной ссылки.
    """

    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("li.next a")
    if link is None:
        return None
    href = (link.get("href") or "").strip()
    if not href:
        return None
    return urljoin(page_url, href)


def extract_book_page(html: str) -> BookPageDetails:
    """Читает страницу одной книги. Отсутствующий блок остаётся None."""

    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("div.product_main h1") or soup.select_one("h1")
    price_node = soup.select_one("div.product_main p.price_color") or soup.select_one("p.price_color")
    rating_node = soup.select_one("div.product_main p.star-rating") or soup.select_one("p.star-rating")
    return BookPageDetails(
        title=_text(title_node),
        price_text=_text(price_node),
        rating_class=_rating_word(rating_node),
        availability_text=_availability_text(soup),
    )


def _extract_card(article, page_url: str) -> RawBook:
    title_link = article.select_one("h3 a")
    title = None
    url = None
    if title_link is not None:
        # Видимый текст на карточке обрезан: «A Light in the ...».
        # Полное название сайт кладёт в атрибут title.
        raw_title = title_link.get("title") or _text(title_link)
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None
        href = (title_link.get("href") or "").strip()
        if href:
            url = urljoin(page_url, href)

    price_node = article.select_one("p.price_color")
    availability_node = article.select_one("p.availability")
    rating_node = article.select_one("p.star-rating")
    return RawBook(
        title=title,
        price_text=_text(price_node),
        rating_class=_rating_word(rating_node),
        availability_text=_text(availability_node),
        url=url,
        source_page=page_url,
    )


def _availability_text(soup: BeautifulSoup) -> str | None:
    # В таблице «Product Information» формулировка полнее, чем в шапке:
    # там есть число экземпляров. Если таблицы нет, берём абзац наличия.
    for row in soup.select("table tr"):
        header = row.find("th")
        cell = row.find("td")
        if header is None or cell is None:
            continue
        if header.get_text(" ", strip=True).lower() == "availability":
            return _text(cell)
    return _text(soup.select_one("p.availability"))


def _rating_word(node) -> str | None:
    """Оставляет слово рейтинга из класса вроде star-rating Three."""

    if node is None:
        return None
    for css_class in node.get("class", []):
        if css_class.lower() != "star-rating":
            return css_class
    return None


def _text(node) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None
