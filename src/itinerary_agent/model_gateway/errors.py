"""模型网关错误类型。

节点据此做确定性降级，而不是把上游异常直接抛给用户。
"""


class ModelError(Exception):
    code = "MODEL_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ModelOutputError(ModelError):
    """结构化输出校验/修复后仍不合法。"""

    code = "MODEL_OUTPUT_INVALID"


class ModelUnavailable(ModelError):
    """主备提供方都不可用。"""

    code = "MODEL_UNAVAILABLE"
