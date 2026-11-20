"""A small JSON Schema check for tools whose source cannot validate (ADR-0003 D4).

The core may not depend on a JSON Schema library, so this covers only what tool
schemas commonly use: ``type``, ``properties``, ``required``, ``additionalProperties:
false``, ``items`` and ``enum``. Any other keyword is ignored, never rejected.
"""

from pydantic import JsonValue

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def check_arguments(schema: dict[str, JsonValue], arguments: dict[str, JsonValue]) -> str | None:
    """Return a message for the model describing the first problem, or None if fine."""
    return _check(schema, arguments, "arguments")


def _check(schema: JsonValue, value: JsonValue, where: str) -> str | None:
    if not isinstance(schema, dict):
        return None
    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else expected
        if isinstance(names, list) and not any(_is(value, str(n)) for n in names):
            return f"{where} must be {' or '.join(str(n) for n in names)}"
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return f"{where} must be one of {enum}"
    if isinstance(value, dict):
        return _check_object(schema, value, where)
    items = schema.get("items")
    if isinstance(value, list) and items is not None:
        for i, item in enumerate(value):
            if problem := _check(items, item, f"{where}[{i}]"):
                return problem
    return None


def _check_object(
    schema: dict[str, JsonValue], value: dict[str, JsonValue], where: str
) -> str | None:
    properties = schema.get("properties")
    props = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    for name in required if isinstance(required, list) else []:
        if str(name) not in value:
            return f"{where}.{name} is required"
    if schema.get("additionalProperties") is False:
        for name in value:
            if name not in props:
                return f"{where}.{name} is not an allowed field"
    for name, item in value.items():
        if name in props and (problem := _check(props[name], item, f"{where}.{name}")):
            return problem
    return None


def _is(value: JsonValue, type_name: str) -> bool:
    allowed = _TYPES.get(type_name)
    if allowed is None:
        return True  # unknown type name: not ours to reject
    if isinstance(value, bool) and type_name in ("integer", "number"):
        return False  # in Python, True is an int; in JSON it is not a number
    if isinstance(value, float) and type_name == "integer":
        return value.is_integer()
    return isinstance(value, allowed)
