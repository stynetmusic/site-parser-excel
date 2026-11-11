"""Некорректный порт отклоняется политикой адресов, а не чужим ValueError."""

import pytest

from books_parser.url_policy import UnsafeUrlError, ensure_allowed_url


@pytest.mark.parametrize(
    "url",
    [
        "https://books.toscrape.com:abc/",
        "https://books.toscrape.com:/",
        "https://books.toscrape.com:99999/",
    ],
)
def test_invalid_port_raises_unsafe_url_error(url):
    with pytest.raises(UnsafeUrlError, match="порт"):
        ensure_allowed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://books.toscrape.com:443/",
        "https://books.toscrape.com/",
    ],
)
def test_standard_https_address_is_allowed(url):
    assert ensure_allowed_url(url) == url


def test_empty_userinfo_is_rejected():
    with pytest.raises(UnsafeUrlError, match="парол"):
        ensure_allowed_url("https://@books.toscrape.com/")
