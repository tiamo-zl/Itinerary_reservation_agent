from itinerary_agent.infra.config import Settings


def test_settings_defaults(monkeypatch):
    # 不读取本地 .env，确保测试断言的是代码默认值。
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.environment == "local"
    assert s.database_url.startswith("postgresql://")
    assert s.embedding_dimensions == 1024
    assert s.adapter_mode == "mock"
