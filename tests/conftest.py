"""Keep desktop integration tests isolated from real LAN PetNest instances."""

from __future__ import annotations

import os


os.environ.setdefault("PETNEST_LAN_AUTO_SYNC", "0")
