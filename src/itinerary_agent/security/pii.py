"""敏感数据格式脱敏。

这里只做“格式级”过滤（手机号、身份证号），业务权限判断在控制层。
网关入参/出参、日志和反馈回流共用同一套规则。
"""

import re

ID_PATTERN = re.compile(r"\d{17}[\dXx]")
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")


def scrub(text: str) -> str:
    """替换文本中的身份证号与手机号。"""
    text = ID_PATTERN.sub("[ID]", text)
    return PHONE_PATTERN.sub("[PHONE]", text)


def _is_identifier_key(key: str | None) -> bool:
    # task_id/trace_id/approval_id 等是系统标识，不能当文本做 PII 替换。
    if not key:
        return False
    return key == "id" or key.endswith("_id")


def scrub_obj(value, key: str | None = None):
    """递归脱敏 dict/list 中的文本，跳过 ID 字段。"""
    if isinstance(value, str):
        return value if _is_identifier_key(key) else scrub(value)
    if isinstance(value, dict):
        return {child_key: scrub_obj(item, child_key)
                for child_key, item in value.items()}
    if isinstance(value, list):
        return [scrub_obj(item, key) for item in value]
    return value
