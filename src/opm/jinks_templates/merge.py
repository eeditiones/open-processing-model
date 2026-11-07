# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deep merge of context maps, the way jinks merges them."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

REPLACE = '$replace'


def _array_key(value: Any) -> Any:
    if isinstance(value, Mapping):
        if 'id' in value:
            return ('id', json.dumps(value['id'], sort_keys=True, default=str))
        return ('json', json.dumps(value, sort_keys=True, default=str))
    if isinstance(value, list):
        return ('json', json.dumps(value, sort_keys=True, default=str))
    return ('value', value)


def _merge_arrays(arrays: list[list[Any]]) -> list[Any]:
    merged: list[Any] = []
    seen: set[Any] = set()
    for array in arrays:
        for value in array:
            key = _array_key(value)
            if key not in seen:
                seen.add(key)
                merged.append(value)
    return merged


def merge_deep(*maps: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge *maps* left to right, the way jinks merges context maps.

    - A scalar replaces an earlier value under the same key.
    - Maps merge recursively. A map holding ``"$replace": true`` replaces the
      earlier map instead; ``"$replace": ["a", "b"]`` replaces only those keys
      and merges the rest.
    - Arrays are concatenated with duplicates dropped: maps with an ``id``
      compare by it, other values by their JSON form.

    ``$replace`` itself never ends up in the result.
    """
    return _merge([m for m in maps if m])


def _copy(value: Any) -> Any:
    return _merge([value]) if isinstance(value, Mapping) else value


def _merge(maps: list[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for incoming in maps:
        replace = incoming.get(REPLACE)
        if replace is True:
            result = {}
        replaced = set(replace) if isinstance(replace, list) else set()
        for key, value in incoming.items():
            if key == REPLACE:
                continue
            current = result.get(key)
            if key in replaced or key not in result:
                result[key] = _copy(value)
            elif isinstance(current, dict) and isinstance(value, Mapping):
                result[key] = _merge([current, value])
            elif isinstance(current, list) and isinstance(value, list):
                result[key] = _merge_arrays([current, value])
            else:
                result[key] = _copy(value)
    return result
