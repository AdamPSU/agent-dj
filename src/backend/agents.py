"""Agent targets for multi-select enable/disable."""

from __future__ import annotations

import sys
from typing import Literal

from backend.ui import GREEN, answered, console

AgentId = Literal["claude", "opencode"]

AGENTS: tuple[tuple[AgentId, str], ...] = (
    ("claude", "Claude Code"),
    ("opencode", "OpenCode"),
)

_LABEL_BY_ID = {aid: label for aid, label in AGENTS}
_ID_BY_LABEL = {label: aid for aid, label in AGENTS}
_VALID = frozenset(_LABEL_BY_ID)


def parse_agent_ids(values: list[str]) -> list[AgentId]:
    out: list[AgentId] = []
    seen: set[str] = set()
    for raw in values:
        v = raw.strip().lower()
        if v not in _VALID:
            raise ValueError(f"unknown agent: {raw}")
        if v in seen:
            continue
        seen.add(v)
        out.append(v)  # type: ignore[arg-type]
    return out


def prompt_agents(
    *,
    selected: list[AgentId] | None = None,
    question: str = "Enable statusline for",
) -> list[AgentId]:
    """Multi-select agents. Space toggles, Enter confirms."""
    from beaupy import Config, select_multiple

    Config.raise_on_interrupt = True
    labels = [label for _, label in AGENTS]
    ids = [aid for aid, _ in AGENTS]
    pre = set(selected or [])
    ticked = [i for i, aid in enumerate(ids) if aid in pre]
    console.print(f"[dim]  {question}[/dim]")
    console.print("[dim]  Space = toggle · Enter = confirm[/dim]")

    try:
        indices = select_multiple(
            labels,
            ticked_indices=ticked or None,
            minimal_count=1,
            return_indices=True,
            tick_style=GREEN,
            cursor_style=GREEN,
        )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("cancelled") from None

    if not indices:
        raise SystemExit("no agents selected")

    result: list[AgentId] = []
    for item in indices:
        if isinstance(item, int) and 0 <= item < len(ids):
            result.append(ids[item])
            continue
        aid = _ID_BY_LABEL.get(str(item))
        if aid is not None:
            result.append(aid)
    if not result:
        raise SystemExit("no agents selected")

    pretty = ", ".join(_LABEL_BY_ID[a] for a in result)
    answered(question, pretty)
    return result
