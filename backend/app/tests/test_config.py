from app.core.config import Settings


def test_settings_declares_expected_defaults() -> None:
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    assert defaults["app_name"] == "helix"
    assert defaults["environment"] == "local"


def test_settings_override_from_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "helix-test")
    monkeypatch.setenv("ENVIRONMENT", "ci")
    settings = Settings()
    assert settings.app_name == "helix-test"
    assert settings.environment == "ci"


def test_settings_reads_database_url_from_env(monkeypatch) -> None:
    url = "postgresql+asyncpg://u:p@somehost:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings()
    assert settings.database_url == url
