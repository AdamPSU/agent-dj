"""Shared data models for Claude DJ.

This module will own track, playback state, decision, and embedding records.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeInfo:
    """Daemon location recorded in the runtime file."""

    pid: int
    host: str
    port: int

    @property
    def base_url(self) -> str:
        """Return the local daemon base URL."""
        return f"http://{self.host}:{self.port}"

    def to_json(self) -> dict[str, int | str]:
        """Serialize runtime info for the runtime file."""
        return {"pid": self.pid, "host": self.host, "port": self.port}

    @classmethod
    def from_json(cls, data: dict[str, object]) -> "RuntimeInfo":
        """Parse runtime info from the runtime file."""
        return cls(pid=int(data["pid"]), host=str(data["host"]), port=int(data["port"]))
