from __future__ import annotations

from petnest.core.fallback_resolver import GLOBAL_PLACEHOLDER, FallbackResolver


def test_resolver_follows_fallbacks_and_breaks_cycles() -> None:
    resolver = FallbackResolver({"error": ("alert",), "alert": ("error", "idle")})
    assert resolver.resolve("error", {"idle"}) == "idle"


def test_resolver_uses_global_placeholder_when_no_action_exists() -> None:
    assert FallbackResolver({}).resolve("unknown", set()) == GLOBAL_PLACEHOLDER
