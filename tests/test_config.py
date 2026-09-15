from pathlib import Path

from loreal_ai_service_intelligence.config import get_settings


def test_loads_selected_environment_file(monkeypatch) -> None:
    config_file = Path(__file__).parents[1] / "config" / "test.example"
    monkeypatch.setenv("APP_CONFIG_FILE", str(config_file))
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_env == "test"
    assert settings.app_port == 8001
    assert settings.app_reload is False
    assert settings.mongodb_database == "loreal_ai_service_intelligence_test"
    assert settings.mongodb_timeout_ms == 3000
    assert settings.mock_api_enabled is True

    get_settings.cache_clear()
