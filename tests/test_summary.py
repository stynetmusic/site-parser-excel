"""Сводка считает только заданные показатели и не заменяет пропуски нулём."""

from datetime import datetime

from tests.helpers import make_book
from books_parser.normalizer import build_summary


COLLECTED_AT = datetime(2026, 11, 11, 12, 0)


def test_summary_counts_and_averages_ignore_missing_values():
    books = [
        make_book(price=10, rating=4, in_stock=True),
        make_book(price=30, rating=2, in_stock=False, availability="Нет в наличии"),
        make_book(
            price=None,
            currency=None,
            rating=None,
            availability=None,
            stock_quantity=None,
            in_stock=None,
        ),
    ]

    summary = build_summary(books, pages_processed=3, collected_at=COLLECTED_AT)

    assert summary.collected_at == COLLECTED_AT
    assert summary.pages_processed == 3
    assert summary.books_found == 3
    assert summary.in_stock_count == 1
    assert summary.out_of_stock_count == 1
    assert summary.average_price == 20
    assert summary.average_rating == 3


def test_empty_summary_has_no_invented_averages():
    summary = build_summary([], pages_processed=0, collected_at=COLLECTED_AT)

    assert summary.books_found == 0
    assert summary.in_stock_count == 0
    assert summary.out_of_stock_count == 0
    assert summary.average_price is None
    assert summary.average_rating is None


def test_unknown_stock_is_not_counted_as_out_of_stock():
    books = [make_book(in_stock=None, availability=None)]

    summary = build_summary(books, pages_processed=1, collected_at=COLLECTED_AT)

    assert summary.books_found == 1
    assert summary.in_stock_count == 0
    assert summary.out_of_stock_count == 0
