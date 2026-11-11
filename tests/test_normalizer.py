"""Проверки цен, рейтинга, наличия и пустых значений."""

import logging

import pytest

from books_parser.models import BookPageDetails, RawBook
from books_parser.normalizer import normalize_book, parse_availability, parse_price, parse_rating


def test_converts_pound_price_to_number_and_currency():
    price, currency, issue = parse_price("£51.77")

    assert price == pytest.approx(51.77)
    assert currency == "GBP"
    assert issue is None


def test_converts_price_with_nbsp_and_comma():
    # Запятая больше не считается десятичным разделителем: иначе £1,234
    # можно ошибочно прочитать как 1.23.
    price, currency, issue = parse_price("£\xa051,77")

    assert price is None
    assert currency is None
    assert issue is not None


def test_converts_mojibake_pound_without_losing_currency():
    price, currency, issue = parse_price("Â£51.77")

    assert price == pytest.approx(51.77)
    assert currency == "GBP"
    assert issue is None


def test_price_without_currency_is_not_guessed():
    price, currency, issue = parse_price("51.77")

    assert price == pytest.approx(51.77)
    assert currency is None
    assert issue == "Валюта в цене не указана"


def test_missing_or_unreadable_price_stays_empty():
    assert parse_price(None) == (None, None, "Цена отсутствует")
    assert parse_price("   ")[0] is None
    assert parse_price("нет цены")[0] is None


def test_regular_price_is_accepted():
    price, currency, issue = parse_price("£51.77")

    assert price == pytest.approx(51.77)
    assert currency == "GBP"
    assert issue is None


def test_zero_price_is_accepted():
    price, currency, issue = parse_price("£0.00")

    assert price == 0
    assert currency == "GBP"
    assert issue is None


def test_negative_price_is_rejected():
    price, currency, issue = parse_price("£-1.20")

    assert price is None
    assert currency is None
    assert issue is not None
    assert "Отрицательная цена" in issue


@pytest.mark.parametrize(
    "raw",
    [
        "£-1.20",
        "-£1.20",
        "£−1.20",
        "£–1.20",
        "(£1.20)",
        "£1,234",
    ],
)
def test_unexpected_price_format_is_not_guessed(raw):
    price, currency, issue = parse_price(raw)

    assert price is None
    assert currency is None
    assert issue
    assert price != pytest.approx(1.20)
    assert price != pytest.approx(1.23)
    assert price != 1234


def test_invalid_price_text_does_not_become_a_number():
    price, currency, issue = parse_price("бесплатно")

    assert price is None
    assert currency is None
    assert issue is not None


def test_converts_rating_words_to_numbers_from_one_to_five():
    assert parse_rating("One") == (1, None)
    assert parse_rating("Two") == (2, None)
    assert parse_rating("Three") == (3, None)
    assert parse_rating("Four") == (4, None)
    assert parse_rating("Five") == (5, None)


def test_unknown_or_missing_rating_stays_empty():
    value, issue = parse_rating("Unknown")
    assert value is None
    assert "Неизвестный рейтинг" in issue
    assert parse_rating(None) == (None, "Рейтинг отсутствует")
    assert parse_rating("6")[0] is None


def test_in_stock_with_quantity():
    in_stock, quantity, label, issue = parse_availability("In stock (22 available)")

    assert in_stock is True
    assert quantity == 22
    assert label == "В наличии"
    assert issue is None


def test_in_stock_without_quantity_does_not_invent_a_number():
    in_stock, quantity, label, issue = parse_availability("  In   stock  ")

    assert in_stock is True
    assert quantity is None
    assert label == "В наличии"
    assert issue is None


def test_out_of_stock_does_not_become_zero():
    in_stock, quantity, label, issue = parse_availability("Out of stock")

    assert in_stock is False
    assert quantity is None
    assert label == "Нет в наличии"
    assert issue is None


def test_unknown_availability_stays_empty():
    in_stock, quantity, label, issue = parse_availability("Скоро")

    assert in_stock is None
    assert quantity is None
    assert label is None
    assert issue is not None
    assert parse_availability(None)[0] is None


def test_missing_book_fields_are_logged_and_left_empty(caplog):
    raw = RawBook(
        title=None,
        price_text=None,
        rating_class=None,
        availability_text=None,
        url=None,
        source_page="https://books.toscrape.com/",
    )

    with caplog.at_level(logging.WARNING):
        record = normalize_book(raw)

    assert record.title is None
    assert record.price is None
    assert record.currency is None
    assert record.rating is None
    assert record.availability is None
    assert record.stock_quantity is None
    assert record.url is None
    assert record.in_stock is None
    assert "Название отсутствует" in record.issues
    assert "Цена отсутствует" in record.issues
    assert "Рейтинг отсутствует" in record.issues
    assert "Наличие не указано" in record.issues
    assert "Ссылка на страницу книги отсутствует" in record.issues
    assert "Название отсутствует" in caplog.text


def test_detail_page_fills_quantity_and_missing_card_fields():
    raw = RawBook(
        title=None,
        price_text=None,
        rating_class=None,
        availability_text="In stock",
        url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        source_page="https://books.toscrape.com/",
    )
    details = BookPageDetails(
        title="A Light in the Attic",
        price_text="£51.77",
        rating_class="Three",
        availability_text="In stock (22 available)",
    )

    record = normalize_book(raw, details, detail_loaded=True)

    assert record.title == "A Light in the Attic"
    assert record.price == pytest.approx(51.77)
    assert record.currency == "GBP"
    assert record.rating == 3
    assert record.stock_quantity == 22
    assert record.in_stock is True
    assert record.issues == []
