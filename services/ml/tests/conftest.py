"""Test settings: a fresh service secret per run and the fake provider (nothing leaves the
machine)."""

import os
import secrets
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import yaml

os.environ["APP_ENV"] = "test"
os.environ["ML_SERVICE_TOKEN"] = secrets.token_urlsafe(40)
os.environ["LLM_PROVIDER"] = "fake"
# Companion tests run without indicator models; indicator tests train their own (see below).
os.environ["ML_MODEL_DIR"] = "/nonexistent/mindmitra-models"

from app.auth import sign_service_token  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers.base import LLMProvider  # noqa: E402
from inference.registry import Registry, load  # noqa: E402
from training.indicators import TABULAR_INDICATORS  # noqa: E402
from training.train import run  # noqa: E402

SUITES = Path(__file__).parent / "suites"


def load_suite(name: str) -> list[dict[str, Any]]:
    data = yaml.safe_load((SUITES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def auth_header(settings: Settings) -> dict[str, str]:
    token = sign_service_token(settings.ml_service_token.get_secret_value())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def trained(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict[str, Any]]]:
    """A quick training run on a small synthetic cohort: (model directory, reports)."""
    root = tmp_path_factory.mktemp("trained")
    reports = run(
        out_dir=root / "models",
        reports_dir=root / "reports",
        students=900,
        quick=True,
        with_transformer=False,
    )
    return root / "models", reports


@pytest.fixture(scope="session")
def registry(trained: tuple[Path, list[dict[str, Any]]]) -> Registry:
    return load(trained[0], tuple(s.name for s in TABULAR_INDICATORS))


@pytest_asyncio.fixture
async def make_client(
    settings: Settings,
) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def _make(
        provider: LLMProvider | None = None, models: Registry | None = None
    ) -> httpx.AsyncClient:
        app = create_app(settings, provider, models)
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ml")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()
