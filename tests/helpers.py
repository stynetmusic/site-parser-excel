"""Небольшие конструкторы данных для тестов."""

from books_parser.models import BookRecord


def make_book(**overrides) -> BookRecord:
    """Собирает запись книги. Переданные поля заменяют учебные значения."""

    data = {
        "title": "A Light in the Attic",
        "price": 10.0,
        "currency": "GBP",
        "rating": 4,
        "availability": "В наличии",
        "stock_quantity": 3,
        "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "in_stock": True,
        "issues": [],
    }
    data.update(overrides)
    return BookRecord(**data)
