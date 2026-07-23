"""Claude-facing auth helpers (shared wizard lives in backend.auth_wizard)."""

from __future__ import annotations

from typing import Any

from backend import auth_wizard


def run() -> dict[str, Any]:
    return auth_wizard.run()
