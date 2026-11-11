"""Проверки извлечения строк из локальных HTML-примеров."""

from books_parser.extractor import extract_book_page, extract_catalog_books, extract_next_page_url


CATALOG = "https://books.toscrape.com/"
PAGE_2 = "https://books.toscrape.com/catalogue/page-2.html"


def test_extracts_full_title_not_truncated_card_text(read_fixture):
    books = extract_catalog_books(read_fixture("catalog_page_1.html"), CATALOG)

    assert books[0].title == "A Light in the Attic"
    assert books[1].title == "Tipping the Velvet"


def test_extracts_price_text_and_rating_class(read_fixture):
    book = extract_catalog_books(read_fixture("catalog_page_1.html"), CATALOG)[0]

    assert book.price_text == "£51.77"
    assert book.rating_class == "Three"
    assert book.availability_text == "In stock"


def test_extracts_absolute_book_link_from_first_page(read_fixture):
    book = extract_catalog_books(read_fixture("catalog_page_1.html"), CATALOG)[0]

    assert book.url == (
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )


def test_extracts_absolute_book_link_from_second_page(read_fixture):
    book = extract_catalog_books(read_fixture("catalog_page_2.html"), PAGE_2)[0]

    assert book.url == "https://books.toscrape.com/catalogue/soumission_998/index.html"


def test_extracts_next_page_and_stops_on_last_page(read_fixture):
    first = read_fixture("catalog_page_1.html")
    second = read_fixture("catalog_page_2.html")

    assert extract_next_page_url(first, CATALOG) == PAGE_2
    assert extract_next_page_url(second, PAGE_2) is None


def test_missing_card_elements_stay_empty(read_fixture):
    books = extract_catalog_books(read_fixture("catalog_missing.html"), CATALOG)

    assert books[0].title is None
    assert books[0].price_text is None
    assert books[0].rating_class is None
    assert books[0].availability_text is None
    assert books[0].url is None

    assert books[1].title == "Только пустая ссылка"
    assert books[1].url is None
    assert books[1].price_text == "нет цены"
    assert books[1].rating_class == "Unknown"
    assert books[1].availability_text == "Скоро"


def test_extracts_stock_phrase_from_book_page(read_fixture):
    details = extract_book_page(read_fixture("book_attic.html"))

    assert details.title == "A Light in the Attic"
    assert details.availability_text == "In stock (22 available)"
    assert details.price_text == "£51.77"
    assert details.rating_class == "Three"


def test_book_page_without_stock_block_returns_empty_fields(read_fixture):
    details = extract_book_page(read_fixture("book_missing.html"))

    assert details.title == "Книга без складских данных"
    assert details.price_text is None
    assert details.rating_class is None
    assert details.availability_text is None
