"""Ошибки загрузки проверяются на поддельной сессии, без интернета."""

from unittest.mock import Mock, patch

import pytest
import requests

from books_parser.http_client import FetchError, PageFetcher, decode_response
from books_parser.url_policy import UnsafeUrlError


URL = "https://books.toscrape.com/"


def response(status: int, text: str = "ok"):
    result = Mock()
    result.status_code = status
    result.content = text.encode("utf-8")
    result.apparent_encoding = "utf-8"
    return result


def fetcher(session, **kwargs) -> PageFetcher:
    defaults = {"timeout": 15, "attempts": 3, "delay": 0, "backoff_base": 0}
    defaults.update(kwargs)
    return PageFetcher(session=session, **defaults)


def test_successful_response_returns_html():
    session = Mock()
    session.get.return_value = response(200, "<html>каталог</html>")

    assert fetcher(session).get_html(URL) == "<html>каталог</html>"
    session.get.assert_called_once_with(URL, timeout=15, allow_redirects=False)


def test_utf8_page_is_not_decoded_as_latin1():
    payload = Mock()
    payload.content = "£51.77".encode("utf-8")
    payload.apparent_encoding = "ISO-8859-1"

    assert decode_response(payload) == "£51.77"


def test_connection_error_is_retried_and_reported_clearly():
    session = Mock()
    session.get.side_effect = requests.ConnectionError("offline")

    with pytest.raises(FetchError, match="сайт недоступен или не отвечает"):
        fetcher(session).get_html(URL)

    assert session.get.call_count == 3


def test_timeout_is_retried_and_then_succeeds():
    session = Mock()
    session.get.side_effect = [requests.Timeout("slow"), response(200, "готово")]

    assert fetcher(session).get_html(URL) == "готово"
    assert session.get.call_count == 2


def test_server_error_is_retried_and_then_succeeds():
    session = Mock()
    session.get.side_effect = [response(503, "busy"), response(200, "готово")]

    assert fetcher(session).get_html(URL) == "готово"
    assert session.get.call_count == 2


def test_repeated_server_error_stops_without_bypass():
    session = Mock()
    session.get.return_value = response(503, "busy")

    with pytest.raises(FetchError, match="не обходит ограничения"):
        fetcher(session).get_html(URL)

    assert session.get.call_count == 3


def test_not_found_is_not_retried():
    session = Mock()
    session.get.return_value = response(404, "missing")

    with pytest.raises(FetchError, match="не найдена"):
        fetcher(session).get_html(URL)

    assert session.get.call_count == 1


def test_forbidden_is_not_retried():
    session = Mock()
    session.get.return_value = response(403, "no")

    with pytest.raises(FetchError, match="не обходит ограничения"):
        fetcher(session).get_html(URL)

    assert session.get.call_count == 1


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://evil.example/book", "посторонн"),
        ("https://localhost/book", "localhost"),
        ("https://127.0.0.1/book", "IP-адрес"),
        ("https://192.168.1.10/book", "IP-адрес"),
        ("https://books.toscrape.com:8443/book", "порт"),
        ("https://books.toscrape.com:abc/", "порт"),
        ("https://books.toscrape.com:/", "порт"),
        ("https://books.toscrape.com:99999/", "порт"),
        ("http://books.toscrape.com/book", "https"),
        ("https://user:secret@books.toscrape.com/book", "паролем"),
    ],
)
def test_forbidden_address_is_not_requested(url, message):
    session = Mock()

    with pytest.raises(UnsafeUrlError, match=message):
        fetcher(session).get_html(url)

    session.get.assert_not_called()


def test_redirect_to_external_domain_is_not_followed():
    session = Mock()
    redirected = response(302, "go away")
    redirected.headers = {"Location": "https://evil.example/phish"}
    session.get.return_value = redirected

    with pytest.raises(FetchError, match="перенаправ"):
        fetcher(session).get_html(URL)

    session.get.assert_called_once_with(URL, timeout=15, allow_redirects=False)


def test_too_many_requests_is_not_retried():
    session = Mock()
    session.get.return_value = response(429, "slow down")

    with pytest.raises(FetchError, match="429"):
        fetcher(session).get_html(URL)

    assert session.get.call_count == 1


def test_delay_is_applied_between_requests_but_not_before_the_first():
    session = Mock()
    session.get.return_value = response(200, "ok")
    client = fetcher(session, delay=0.25)

    with patch("books_parser.http_client.time.sleep") as sleep:
        client.get_html(URL)
        client.get_html("https://books.toscrape.com/catalogue/page-2.html")

    sleep.assert_called_once_with(0.25)
