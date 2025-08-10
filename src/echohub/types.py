from __future__ import annotations

import json
from typing import TypeAlias, cast

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def as_object(value: JsonValue | None) -> JsonObject:
    return value if isinstance(value, dict) else {}


def as_array(value: JsonValue | None) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def as_str(value: JsonValue | None, default: str = "") -> str:
    return value if isinstance(value, str) else default


def as_int(value: JsonValue | None, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def as_float(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_bool(value: JsonValue | None, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and is_json_value(item) for key, item in value.items()
        )
    return False


def decode_json_value(text: str) -> JsonValue:
    # The stdlib deliberately types json.loads as Any. Collapse that unsafe edge
    # immediately to object, validate the full recursive JSON shape, then expose
    # the project's concrete JsonValue type everywhere else.
    value: object = json.loads(text)  # pyright: ignore[reportAny]
    if not is_json_value(value):
        raise ValueError("Decoded value is not valid JSON")
    return cast(JsonValue, value)


def decode_json_object(text: str) -> JsonObject:
    value = decode_json_value(text)
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object")
    return value
