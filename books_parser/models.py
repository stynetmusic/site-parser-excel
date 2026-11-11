"""Структуры данных, которые переходят между модулями программы."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawBook:
    """Сырые строки с карточки каталога, ещё без проверки и приведения типов.

    Пустые поля остаются None. Подставлять число или текст «на глаз» нельзя:
    отсутствие данных — тоже результат, его позже фиксируют в журнале.
    """

    title: str | None
    price_text: str | None
    rating_class: str | None
    availability_text: str | None
    url: str | None
    source_page: str


@dataclass
class BookPageDetails:
    """Фрагменты со страницы конкретной книги.

    Количество экземпляров на карточке каталога не указано. Оно встречается
    только здесь, в строке вида «In stock (22 available)».
    """

    title: str | None
    price_text: str | None
    rating_class: str | None
    availability_text: str | None


@dataclass
class BookRecord:
    """Проверенная запись о книге, готовая к записи в Excel."""

    title: str | None
    price: float | None
    currency: str | None
    rating: int | None
    availability: str | None
    stock_quantity: int | None
    url: str | None
    in_stock: bool | None
    issues: list[str] = field(default_factory=list)


@dataclass
class CollectionResult:
    """Итог обхода каталога.

    completed=False означает, что часть страниц получить не удалось.
    Уже собранные книги при этом не выбрасываются.
    """

    books: list[BookRecord]
    pages_processed: int
    completed: bool
    error_message: str | None = None


@dataclass
class CatalogSummary:
    """Показатели листа «Сводка». Других метрик программа не считает."""

    collected_at: datetime
    pages_processed: int
    books_found: int
    in_stock_count: int
    out_of_stock_count: int
    average_price: float | None
    average_rating: float | None
