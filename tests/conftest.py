import json
from pathlib import Path

import pytest

from radar import config

FIXTURES = Path(__file__).parent / "fixtures"


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def data(name: str):
    return json.loads(text(name))


@pytest.fixture(scope="session")
def cfg():
    return config.load()
