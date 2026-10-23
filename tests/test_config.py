from pathlib import Path

from itinerary_agent.infra.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.env == "local"
    assert s.sqlite_path == Path("./data/itinerary.db")
    assert s.embedding_dimensions == 1024
    assert s.adapter_mode == "mock"
