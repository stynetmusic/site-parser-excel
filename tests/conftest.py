"""Общие помощники тестов. Сетевые вызовы здесь не выполняются."""

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def read_fixture():
    """Читает локальный HTML-пример по имени файла."""

    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read
