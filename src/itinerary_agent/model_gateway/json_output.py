"""模型结构化输出的提取与校验。"""

import json
import re

import jsonschema


def extract_json_object(text: str) -> dict:
    """从模型输出中提取 JSON 对象，兼容代码块和前后解释文字。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output is not a JSON object")
    return json.loads(text[start:end + 1])


def parse_and_validate(text: str, schema: dict) -> dict:
    """解析并校验 JSON；失败抛 ValueError。"""
    data = extract_json_object(text)
    jsonschema.validate(data, schema)
    return data
