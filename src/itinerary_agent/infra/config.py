"""应用配置。

配置只描述"接什么外部依赖、用什么模式运行"，不承载业务规则。
密钥全部从环境变量或 .env 读取，绝不写进代码或图状态。
"""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。

    环境变量名与字段名一致（大小写不敏感），例如 `database_url`
    可由 `DATABASE_URL` 覆盖。demo 默认可在无 API Key 的情况下启动，
    但调用真实模型前必须提供对应 Key。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 运行环境与基础设施。
    environment: Literal["local", "test", "staging", "prod"] = "local"
    database_url: str = (
        "postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary"
    )
    database_pool_min: int = 1
    database_pool_max: int = 10
    redis_url: str = "redis://127.0.0.1:56379/0"

    # 鉴权：mock 仅允许 local/test；生产必须 jwt/oidc。
    auth_mode: Literal["mock", "jwt", "oidc"] = "mock"
    jwt_secret: str | None = None
    jwt_issuer: str = "itinerary-agent-local"
    jwt_audience: str = "itinerary-agent"
    oidc_issuer: str | None = None
    oidc_audience: str = "itinerary-agent"
    oidc_jwks_url: str | None = None

    # 后台 worker：outbox 轮询与租约。
    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 5
    outbox_lease_seconds: int = 60
    # 任务恢复租约：防止用户 resume 与 worker 并发恢复同一任务。
    task_lease_seconds: int = 300

    # 聊天模型：所有档位都走 OpenAI 兼容协议，便于切换厂商。
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    model_light: str = "deepseek-chat"
    model_standard: str = "deepseek-chat"
    model_reasoning: str = "deepseek-reasoner"
    model_timeout_seconds: float = 30.0
    model_max_retries: int = 2
    primary_provider_name: str = "deepseek"

    # 备用提供方：主模型失败时切换；默认复用 DashScope 的兼容接口。
    model_fallback_enabled: bool = True
    fallback_provider_name: str = "dashscope"
    fallback_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    fallback_api_key: str | None = None
    fallback_model_light: str = "qwen-plus"
    fallback_model_standard: str = "qwen-plus"
    fallback_model_reasoning: str = "qwen-plus"

    # 模型缓存与价格表。
    llm_cache_backend: Literal["auto", "redis", "postgres", "none"] = "auto"
    llm_cache_ttl_seconds: int = 86400
    model_pricing_file: str = "config/pricing.yaml"

    # 接口限流：按用户/租户的每分钟固定窗口。
    rate_limit_enabled: bool = True
    rate_limit_chat_per_minute: int = 30
    rate_limit_approval_per_minute: int = 60
    rate_limit_feedback_per_minute: int = 20

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

    @model_validator(mode="after")
    def _validate_auth_for_environment(self):
        """生产环境禁止可伪造的 mock 鉴权，并校验必需配置。"""
        if self.environment == "prod":
            if self.auth_mode == "mock":
                raise ValueError(
                    "AUTH_MODE=mock is not allowed when ENVIRONMENT=prod"
                )
            if self.auth_mode == "jwt" and not self.jwt_secret:
                raise ValueError("JWT_SECRET is required when AUTH_MODE=jwt")
            if self.auth_mode == "oidc" and not (
                self.oidc_issuer and self.oidc_jwks_url
            ):
                raise ValueError(
                    "OIDC_ISSUER and OIDC_JWKS_URL are required when "
                    "AUTH_MODE=oidc"
                )
        return self
