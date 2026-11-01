"""真实 HTTP 适配器。

只通过注入的 `JsonHttpClient` 访问外部系统；超时、重试、trace 透传和
错误分类统一在 client，业务适配器只做协议映射。
"""
