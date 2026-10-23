from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    sqlite_path: Path = Path("./data/itinerary.db")

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    model_light: str = "deepseek-chat"
    model_standard: str = "deepseek-chat"
    model_reasoning: str = "deepseek-reasoner"

    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3.7-text-embedding-flash"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 20

    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_collection: str = "itinerary_policy_clauses_v1"

    adapter_mode: Literal["mock", "real"] = "mock"
    model_mode: Literal["scripted", "live"] = "scripted"
    trace_retention_days: int = 7
    capture_prompt: bool = False
    mock_approval_delay_seconds: float = 5.0

    policy_version: str = "2026.1"
    policy_seed_top_k: int = 8
    policy_graph_hops: int = 2
    policy_max_expanded_clauses: int = 20
