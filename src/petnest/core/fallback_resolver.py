"""宠物动作缺失时的有限 fallback 解析。"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

GLOBAL_PLACEHOLDER = "__petnest_placeholder__"


class FallbackResolver:
    """以广度优先顺序解析动作，循环或超深链路不会无限递归。"""

    def __init__(self, fallbacks: Mapping[str, Sequence[str]], max_depth: int = 16) -> None:
        if max_depth < 1:
            raise ValueError("max_depth 必须为正数")
        self._fallbacks = {name: tuple(candidates) for name, candidates in fallbacks.items()}
        self._max_depth = max_depth

    def resolve(self, requested: str, available: Collection[str]) -> str:
        """返回可用动作，或永远存在的全局占位动作。"""
        available_actions = set(available)
        pending: list[tuple[str, int]] = [(requested, 0)]
        seen: set[str] = set()
        while pending:
            candidate, depth = pending.pop(0)
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate in available_actions:
                return candidate
            if depth < self._max_depth:
                pending.extend((fallback, depth + 1) for fallback in self._fallbacks.get(candidate, ()))
        return GLOBAL_PLACEHOLDER
