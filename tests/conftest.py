from collections.abc import Iterator

import pytest

from loreal_ai_service_intelligence.config import get_settings


@pytest.fixture(autouse=True)
def isolate_runtime_config(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[None]:
    """自动化测试不得读取开发者本地 `.env` 或调用真实 LLM。"""
    monkeypatch.setenv("APP_CONFIG_FILE", str(tmp_path / "missing-test.env"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
