import importlib


def test_validate_config_reports_missing_tokens(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)              # keep the repo's real .env out of reach
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import config
    importlib.reload(config)
    problems = config.validate_config()
    assert any("DISCORD_TOKEN" in p for p in problems)
    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_validate_config_ok(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    import config
    importlib.reload(config)
    assert config.validate_config() == []


def test_redact_strips_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "supersecrettoken")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc")
    import config, logging_util
    importlib.reload(config)
    importlib.reload(logging_util)
    out = logging_util.redact("err supersecrettoken and sk-ant-abc done")
    assert "supersecrettoken" not in out
    assert "sk-ant-abc" not in out
