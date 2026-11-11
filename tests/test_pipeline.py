"""Обход каталога на локальных страницах: следующая страница и карточки книг."""

import pytest

from books_parser.http_client import FetchError, SiteLimitError
from books_parser.pipeline import collect_books


START = "https://books.toscrape.com/"
PAGE_2 = "https://books.toscrape.com/catalogue/page-2.html"
ATTIC = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
VELVET = "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html"
SOUMISSION = "https://books.toscrape.com/catalogue/soumission_998/index.html"


class MapFetcher:
    """Отдаёт заранее сохранённый HTML и запоминает запрошенные адреса."""

    def __init__(self, pages: dict[str, str], fail: set[str] | None = None) -> None:
        self.pages = pages
        self.fail = fail or set()
        self.calls: list[str] = []

    def get_html(self, url: str) -> str:
        self.calls.append(url)
        if url in self.fail:
            raise FetchError(
                f"Не удалось открыть страницу {url}: сайт недоступен или не отвечает.",
                url,
            )
        if url not in self.pages:
            raise FetchError(f"Страница не найдена: {url}", url)
        return self.pages[url]


def _pages(read_fixture) -> dict[str, str]:
    return {
        START: read_fixture("catalog_page_1.html"),
        PAGE_2: read_fixture("catalog_page_2.html"),
        ATTIC: read_fixture("book_attic.html"),
        VELVET: read_fixture("book_velvet.html"),
        SOUMISSION: read_fixture("book_out_of_stock.html"),
    }


def test_collects_all_local_pages_and_stock_quantities(read_fixture):
    fetcher = MapFetcher(_pages(read_fixture))

    result = collect_books(fetcher, START)

    assert result.completed is True
    assert result.pages_processed == 2
    assert [book.title for book in result.books] == [
        "A Light in the Attic",
        "Tipping the Velvet",
        "Soumission",
    ]
    assert [book.stock_quantity for book in result.books] == [22, 19, None]
    assert [book.in_stock for book in result.books] == [True, True, False]
    assert result.books[0].price == pytest.approx(51.77)
    assert result.books[0].rating == 3
    assert result.books[2].availability == "Нет в наличии"
    assert result.books[2].stock_quantity is None
    assert fetcher.calls[0] == START
    assert fetcher.calls.index(ATTIC) < fetcher.calls.index(PAGE_2)


def test_max_pages_stops_before_the_next_catalog_page(read_fixture):
    fetcher = MapFetcher(_pages(read_fixture))

    result = collect_books(fetcher, START, max_pages=1)

    assert result.completed is False
    assert "предел" in (result.error_message or "")
    assert result.pages_processed == 1
    assert len(result.books) == 2
    assert PAGE_2 not in fetcher.calls


def test_failed_book_page_keeps_card_and_leaves_quantity_empty(read_fixture):
    pages = _pages(read_fixture)
    fetcher = MapFetcher(pages, fail={ATTIC})

    result = collect_books(fetcher, START)

    assert result.completed is True
    assert result.books[0].title == "A Light in the Attic"
    assert result.books[0].price == pytest.approx(51.77)
    assert result.books[0].stock_quantity is None
    assert any("количество экземпляров неизвестно" in issue for issue in result.books[0].issues)
    assert result.books[1].stock_quantity == 19


def test_unavailable_first_page_raises_clear_error(read_fixture):
    fetcher = MapFetcher({}, fail={START})

    with pytest.raises(FetchError, match="сайт недоступен или не отвечает"):
        collect_books(fetcher, START)


def test_later_catalog_page_failure_returns_partial_result(read_fixture):
    fetcher = MapFetcher(_pages(read_fixture), fail={PAGE_2})

    result = collect_books(fetcher, START)

    assert result.completed is False
    assert result.pages_processed == 1
    assert len(result.books) == 2
    assert "недоступен" in (result.error_message or "")


class ScriptedFetcher:
    """Отдаёт страницы и может остановить выбранный адрес особой ошибкой."""

    def __init__(self, pages: dict[str, str], stops: dict[str, Exception] | None = None) -> None:
        self.pages = pages
        self.stops = stops or {}
        self.calls: list[str] = []

    def get_html(self, url: str) -> str:
        self.calls.append(url)
        if url in self.stops:
            raise self.stops[url]
        if url not in self.pages:
            raise FetchError(f"Страница не найдена: {url}", url)
        return self.pages[url]


def _catalog(urls: list[str], next_href: str | None = None) -> str:
    cards = []
    for index, url in enumerate(urls, start=1):
        cards.append(
            f"""
            <article class="product_pod">
              <p class="star-rating Three"></p>
              <h3><a href="{url}" title="Book {index}">Book {index}</a></h3>
              <p class="price_color">£10.00</p>
              <p class="availability">In stock</p>
            </article>
            """
        )
    next_link = ""
    if next_href:
        next_link = f'<li class="next"><a href="{next_href}">next</a></li>'
    return "<html><body>" + "".join(cards) + next_link + "</body></html>"


def test_empty_catalog_page_is_not_a_successful_run():
    fetcher = ScriptedFetcher({START: "<html><body><p>пусто</p></body></html>"})

    result = collect_books(fetcher, START)

    assert result.completed is False
    assert result.books == []
    assert "нет карточек" in (result.error_message or "")
    assert fetcher.calls == [START]


@pytest.mark.parametrize("status", [403, 429])
def test_site_limit_stops_before_the_next_book(read_fixture, status):
    pages = _pages(read_fixture)
    message = f"код {status}"
    fetcher = ScriptedFetcher(
        pages,
        stops={ATTIC: SiteLimitError(message, ATTIC, status=status)},
    )

    result = collect_books(fetcher, START, max_pages=1)

    assert result.completed is False
    assert status == 403 or "429" in (result.error_message or "") or str(status) in (
        result.error_message or ""
    )
    assert fetcher.calls == [START, ATTIC]
    assert VELVET not in fetcher.calls


def test_external_book_link_is_not_requested():
    external = "https://evil.example/book"
    local = "https://books.toscrape.com/catalogue/local-book/index.html"
    html = _catalog([external, local])
    fetcher = ScriptedFetcher({START: html, local: "<html></html>"})

    result = collect_books(fetcher, START)

    assert result.completed is False
    assert "посторонн" in (result.error_message or "")
    assert external not in fetcher.calls
    assert local not in fetcher.calls


def test_external_next_page_is_not_requested(read_fixture):
    html = _catalog(
        ["https://books.toscrape.com/catalogue/only-book/index.html"],
        next_href="https://evil.example/next",
    )
    book_url = "https://books.toscrape.com/catalogue/only-book/index.html"
    fetcher = ScriptedFetcher({START: html, book_url: read_fixture("book_attic.html")})

    result = collect_books(fetcher, START)

    assert result.completed is False
    assert "посторонн" in (result.error_message or "")
    assert "https://evil.example/next" not in fetcher.calls


def test_five_book_errors_in_a_row_stop_the_crawl():
    urls = [
        f"https://books.toscrape.com/catalogue/book-{index}/index.html" for index in range(1, 7)
    ]
    fetcher = ScriptedFetcher({START: _catalog(urls)})

    result = collect_books(fetcher, START)

    assert result.completed is False
    assert "подряд" in (result.error_message or "")
    assert fetcher.calls == [START, *urls[:5]]
    assert urls[5] not in fetcher.calls


def test_successful_book_page_resets_consecutive_errors():
    urls = [
        f"https://books.toscrape.com/catalogue/reset-{index}/index.html" for index in range(1, 6)
    ]
    ok = urls[1]
    fetcher = ScriptedFetcher(
        {START: _catalog(urls), ok: "<html><p class='availability'>In stock (3 available)</p></html>"}
    )

    result = collect_books(fetcher, START, max_consecutive_book_errors=2)

    assert result.completed is False
    assert fetcher.calls == [START, urls[0], urls[1], urls[2], urls[3]]
    assert urls[4] not in fetcher.calls


def test_default_page_cap_marks_unfinished_catalog_incomplete(read_fixture):
    fetcher = MapFetcher(_pages(read_fixture))

    result = collect_books(fetcher, START, max_pages=None, page_limit=1)

    assert result.completed is False
    assert result.pages_processed == 1
    assert "предел" in (result.error_message or "")
    assert PAGE_2 not in fetcher.calls
