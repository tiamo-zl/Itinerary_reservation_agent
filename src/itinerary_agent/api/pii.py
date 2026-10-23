"""敏感数据格式脱敏。

这里只做“格式级”过滤（手机号、身份证号），业务权限判断在控制层。
网关对入参和 SSE 出参都调用同一套规则，避免模型把敏感字段带回去。
"""

import re

ID_PATTERN = re.compile(r"\d{17}[\dXx]")
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")


def scrub(text: str) -> str:
    """替换文本中的身份证号与手机号。"""
    text = ID_PATTERN.sub("[ID]", text)
    return PHONE_PATTERN.sub("[PHONE]", text)


def scrub_obj(value):
    """递归脱敏 dict/list 中的字符串，供 SSE 事件使用。"""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {key: scrub_obj(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_obj(item) for item in value]
    return value
