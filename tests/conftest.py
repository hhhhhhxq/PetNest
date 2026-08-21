"""Keep desktop integration tests isolated from real LAN PetNest instances."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


os.environ.setdefault("PETNEST_LAN_AUTO_SYNC", "0")


@pytest.fixture(autouse=True)
def isolate_codex_home_from_real_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default-enabled linkage tests must never inspect the developer's real sessions."""
    isolated_home = tmp_path / "isolated-user-home"
    monkeypatch.setenv("CODEX_HOME", str(isolated_home / ".codex-profile"))
    monkeypatch.setenv("USERPROFILE", str(isolated_home))
    monkeypatch.setenv("HOME", str(isolated_home))

    def unavailable_app_home() -> Path:
        raise RuntimeError("Codex app-server disabled in isolated tests")

    monkeypatch.setattr("petnest.app._fetch_codex_home_for_discovery", unavailable_app_home)
