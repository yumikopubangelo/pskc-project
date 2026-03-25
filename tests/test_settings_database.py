from config.settings import AppSettings


def test_database_url_defaults_to_project_data_file(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    settings = AppSettings()

    assert settings.database_url.startswith("sqlite:///")
    assert settings.database_path.replace("\\", "/").endswith("/data/pskc.db")


def test_database_url_uses_explicit_environment_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom/runtime.db")
    monkeypatch.delenv("DATABASE_PATH", raising=False)

    settings = AppSettings()

    assert settings.database_url == "sqlite:///custom/runtime.db"
