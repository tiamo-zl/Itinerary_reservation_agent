"""模型价格表与成本计算。

价格随合同/地域变化；`config/pricing.yaml` 只是部署默认值，
未知模型按 0 成本记录并保留 token 数，避免阻塞主流程。
"""

from pathlib import Path

import yaml


class PriceTable:
    def __init__(self, providers: dict | None = None):
        self.providers = providers or {}

    @classmethod
    def load(cls, path: str) -> "PriceTable":
        file = Path(path)
        if not file.exists():
            return cls({})
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        return cls(data.get("providers", {}))

    def cost(self, provider: str, model: str, prompt_tokens: int,
             completion_tokens: int) -> float:
        price = self.providers.get(provider, {}).get(model)
        if not price:
            return 0.0
        return (
            prompt_tokens / 1_000_000 * float(price.get("input_per_1m", 0))
            + completion_tokens / 1_000_000 * float(price.get("output_per_1m", 0))
        )
