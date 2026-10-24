"""应用配置。

配置只描述"接什么外部依赖、用什么模式运行"，不承载业务规则。
密钥全部从环境变量或 .env 读取，绝不写进代码或图状态。
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。

    环境变量名与字段名一致（大小写不敏感），例如 `sqlite_path`
    可由 `SQLITE_PATH` 覆盖。demo 默认可在无 API Key 的情况下启动，
    但调用真实模型前必须提供对应 Key。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 运行环境与本地存储。
    env: str = "local"
    sqlite_path: Path = Path("./data/itinerary.db")

    # 聊天模型：所有档位都走 OpenAI 兼容协议，便于切换厂商。
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    model_light: str = "deepseek-chat"
    model_standard: str = "deepseek-chat"
    model_reasoning: str = "deepseek-reasoner"

    # Embedding：阿里云百炼的 OpenAI 兼容接口。
    # 维度在建 Milvus collection 时确定，后续不能混用不同维度。
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3.7-text-embedding-flash"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 20

    # 制度向量库：使用本地已有的 Milvus 服务，不启动嵌入式版本。
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_collection: str = "itinerary_policy_clauses_v1"

    # 运行模式：
    # - adapter_mode=mock：外部系统全部使用模拟实现
    # - model_mode=scripted：不调用真实模型，便于跑测试和离线演示
    adapter_mode: Literal["mock", "real"] = "mock"
    model_mode: Literal["scripted", "live"] = "scripted"
    trace_retention_days: int = 7
    capture_prompt: bool = False
    mock_approval_delay_seconds: float = 5.0
    # 默认手动审批，审批页才能真正展示待办；需要自动通过时显式开启。
    mock_approval_auto_approve: bool = False

    # 制度检索参数：种子数、图扩展跳数和上下文上限。
    policy_version: str = "2026.1"
    policy_seed_top_k: int = 8
    policy_graph_hops: int = 2
    policy_max_expanded_clauses: int = 20
