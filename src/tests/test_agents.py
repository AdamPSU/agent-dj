from unittest.mock import patch

import pytest

from backend.agents import parse_agent_ids, prompt_agents


def test_parse_agent_ids_order_and_dedupe() -> None:
    assert parse_agent_ids(["opencode", "claude", "claude", "pi"]) == [
        "opencode",
        "claude",
        "pi",
    ]


def test_parse_agent_ids_unknown() -> None:
    with pytest.raises(ValueError, match="unknown"):
        parse_agent_ids(["nope"])


def test_prompt_agents_uses_indices() -> None:
    with patch("beaupy.select_multiple", return_value=[0, 1]) as sm:
        out = prompt_agents(selected=["claude", "opencode"])
    assert out == ["claude", "opencode"]
    assert sm.call_args.kwargs.get("return_indices") is True
    assert sm.call_args.kwargs.get("tick_style") == "#1DB954"
