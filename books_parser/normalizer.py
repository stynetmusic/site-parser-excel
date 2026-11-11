"""Проверка и приведение сырых строк к числам и коротким подписям."""

import logging
import re

from books_parser.models import BookPageDetails, BookRecord, CatalogSummary, RawBook


logger = logging.getLogger(__name__)

# На сайте рейтинг — это слово в CSS-классе, а не цифра.
RATING_BY_WORD = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}

CURRENCY_BY_SYMBOL = {
    "£": "GBP",
    "Â£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
}

# Цена на Books to Scrape целиком выглядит как £51.77: символ, целое и ровно две цифры после точки.
# Совпадение с куском строки запрещено, иначе «£1,234» или «£-1.20» можно прочитать неверно.
_CATALOG_PRICE_RE = re.compile(r"^(?P<symbol>Â£|£)\s*(?P<amount>\d+\.\d{2})$")
_PLAIN_AMOUNT_RE = re.compile(r"^(?P<amount>\d+\.\d{2})$")
_NEGATIVE_MARKS = ("-", "−", "–", "—")
_QUANTITY_RE = re.compile(r"(\d+)\s+available", re.IGNORECASE)
_CURRENCY_CODE_RE = re.compile(r"\b(GBP|USD|EUR|JPY)\b", re.IGNORECASE)


def parse_price(raw: str | None) -> tuple[float | None, str | None, str | None]:
    """Превращает «£51.77» в число 51.77 и код валюты GBP.

    Возвращает тройку: цена, валюта, описание проблемы.
    Если валюта или число не распознаны, соответствующее значение — None.
    Валюта не подставляется по умолчанию. Отрицательная цена тоже не
    превращается в положительную: такая строка отклоняется целиком.
    """

    text = _clean(raw)
    if text is None:
        return None, None, "Цена отсутствует"
    if any(mark in text for mark in _NEGATIVE_MARKS):
        return None, None, f"Отрицательная цена: {text}"
    if text.startswith("(") or text.endswith(")"):
        return None, None, f"Некорректный формат цены: {text}"

    catalog_price = _CATALOG_PRICE_RE.fullmatch(text)
    plain_amount = _PLAIN_AMOUNT_RE.fullmatch(text)
    if catalog_price is None and plain_amount is None:
        return None, None, f"Некорректный формат цены: {text}"

    amount = (catalog_price or plain_amount).group("amount")
    try:
        price = round(float(amount), 2)
    except ValueError:
        return None, None, f"Некорректный формат цены: {text}"
    if price < 0:
        return None, None, f"Отрицательная цена: {text}"

    if catalog_price is None:
        return price, None, "Валюта в цене не указана"
    currency = _detect_currency(catalog_price.group("symbol"))
    if currency is None:
        return None, None, f"Некорректный формат цены: {text}"
    return price, currency, None


def parse_rating(rating_class: str | None) -> tuple[int | None, str | None]:
    """Превращает класс One…Five в целое число от 1 до 5."""

    text = _clean(rating_class)
    if text is None:
        return None, "Рейтинг отсутствует"

    key = text.lower()
    if key in RATING_BY_WORD:
        return RATING_BY_WORD[key], None
    if key.isdigit() and int(key) in range(1, 6):
        return int(key), None
    return None, f"Неизвестный рейтинг: {text}"


def parse_availability(
    raw: str | None,
) -> tuple[bool | None, int | None, str | None, str | None]:
    """Определяет наличие и, если оно написано, количество экземпляров.

    «Out of stock» без числа не превращается в ноль: количество остаётся пустым.
    Возвращает: в наличии, количество, подпись на русском, описание проблемы.
    """

    text = _clean(raw)
    if text is None:
        return None, None, None, "Наличие не указано"

    lowered = text.lower()
    quantity = None
    quantity_match = _QUANTITY_RE.search(lowered)
    if quantity_match:
        quantity = int(quantity_match.group(1))

    # «out of stock» проверяется раньше «in stock»: иначе слово stock
    # можно было бы перепутать, если когда-нибудь изменить условие.
    if "out of stock" in lowered:
        return False, quantity, "Нет в наличии", None
    if "in stock" in lowered:
        return True, quantity, "В наличии", None
    return None, quantity, None, f"Не удалось определить наличие: {text}"


def normalize_book(
    raw: RawBook,
    details: BookPageDetails | None = None,
    detail_loaded: bool = False,
) -> BookRecord:
    """Собирает запись книги и записывает каждую проблему в журнал.

    Со страницы книги заполняются только пустые поля карточки. Наличие
    со страницы книги важнее карточки, потому что там указано количество.
    """

    title = _clean(raw.title)
    price_text = _clean(raw.price_text)
    rating_class = _clean(raw.rating_class)
    availability_text = _clean(raw.availability_text)
    url = _clean(raw.url)

    if details is not None:
        if title is None:
            title = _clean(details.title)
        if price_text is None:
            price_text = _clean(details.price_text)
        if rating_class is None:
            rating_class = _clean(details.rating_class)
        detailed_availability = _clean(details.availability_text)
        if detailed_availability is not None:
            availability_text = detailed_availability

    issues: list[str] = []
    if title is None:
        issues.append("Название отсутствует")

    price, currency, price_issue = parse_price(price_text)
    if price_issue:
        issues.append(price_issue)

    rating, rating_issue = parse_rating(rating_class)
    if rating_issue:
        issues.append(rating_issue)

    in_stock, quantity, availability, availability_issue = parse_availability(availability_text)
    if availability_issue:
        issues.append(availability_issue)

    if url is None:
        issues.append("Ссылка на страницу книги отсутствует")
    elif not detail_loaded:
        issues.append("Страница книги не загружена, количество экземпляров неизвестно")
    elif quantity is None:
        issues.append("Количество доступных экземпляров не указано")

    record = BookRecord(
        title=title,
        price=price,
        currency=currency,
        rating=rating,
        availability=availability,
        stock_quantity=quantity,
        url=url,
        in_stock=in_stock,
        issues=issues,
    )
    for issue in issues:
        where = url or raw.source_page
        logger.warning("Проблема в данных (%s): %s", where, issue)
    return record


def build_summary(books: list[BookRecord], pages_processed: int, collected_at) -> CatalogSummary:
    """Считает только те показатели, которые есть в задании.

    Средняя цена и средний рейтинг считаются по книгам, где значение удалось
    прочитать. Пустые поля не заменяются нулём и не участвуют в среднем.
    Книга с неизвестным наличием не попадает ни в одну из двух групп наличия.
    """

    prices = [book.price for book in books if book.price is not None]
    ratings = [book.rating for book in books if book.rating is not None]
    return CatalogSummary(
        collected_at=collected_at,
        pages_processed=pages_processed,
        books_found=len(books),
        in_stock_count=sum(1 for book in books if book.in_stock is True),
        out_of_stock_count=sum(1 for book in books if book.in_stock is False),
        average_price=(sum(prices) / len(prices)) if prices else None,
        average_rating=(sum(ratings) / len(ratings)) if ratings else None,
    )


def _detect_currency(text: str) -> str | None:
    for symbol, code in CURRENCY_BY_SYMBOL.items():
        if symbol in text:
            return code
    code_match = _CURRENCY_CODE_RE.search(text)
    if code_match:
        return code_match.group(1).upper()
    return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.replace("\xa0", " ").split())
    return text or None
