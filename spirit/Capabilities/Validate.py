"""
轻量校验：只查 JSON Schema 里最要紧的几样——必填、类型、多余字段。

不做完整 JSON Schema 实现（那要引依赖）；能力够用就行：
  - 模型给参数：必填 / 类型 / additionalProperties
  - 能力给配置：必填 / 类型
"""

_TYPES = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _type_ok(expected, value):
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    python_type = _TYPES.get(expected)
    if python_type is None:
        return True
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, python_type)


def _check(schema, data, where):
    if not isinstance(schema, dict):
        return None
    if not isinstance(data, dict):
        return f"{where} 必须是对象"

    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in data:
            return f"缺少必填参数：{name}"

    for name, value in data.items():
        rule = properties.get(name)
        if rule is None:
            if schema.get("additionalProperties") is False:
                return f"不认识的参数：{name}"
            continue
        expected = rule.get("type")
        if expected and not _type_ok(expected, value):
            return f"参数 {name} 类型应为 {expected}"

    return None


def validate_arguments(schema, arguments):
    """模型给的参数；返回错误文本或 None。"""
    return _check(schema or {}, arguments, "参数")


def validate_config(schema, config):
    """能力自己的配置；返回错误文本或 None。"""
    return _check(schema or {}, config, "配置")
