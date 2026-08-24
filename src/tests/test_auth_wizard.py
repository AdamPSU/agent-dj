from unittest.mock import patch

from backend import auth_wizard


def test_enable_agents_claude_only() -> None:
    with (
        patch(
            "backend.auth_wizard.claude_statusline.ensure_installed",
            return_value={"ok": True, "action": "installed"},
        ) as claude,
        patch(
            "backend.auth_wizard.opencode_statusline.ensure_installed",
        ) as oc,
    ):
        out = auth_wizard.enable_agents(["claude"])
    claude.assert_called_once_with()
    oc.assert_not_called()
    assert out["ok"] is True
    assert out["agents"]["claude"]["ok"] is True


def test_enable_agents_opencode_failure_surfaces() -> None:
    with (
        patch(
            "backend.auth_wizard.claude_statusline.ensure_installed",
            return_value={"ok": True, "action": "installed"},
        ),
        patch(
            "backend.auth_wizard.opencode_statusline.ensure_installed",
            side_effect=RuntimeError("no npm"),
        ),
    ):
        out = auth_wizard.enable_agents(["claude", "opencode"])
    assert out["ok"] is False
    assert out["agents"]["opencode"]["error"] == "no npm"


def test_disable_agents() -> None:
    with (
        patch(
            "backend.auth_wizard.claude_statusline.uninstall",
            return_value={"ok": True, "action": "disabled"},
        ) as claude,
        patch(
            "backend.auth_wizard.opencode_statusline.uninstall",
            return_value=None,
        ) as oc,
    ):
        out = auth_wizard.disable_agents(["claude", "opencode"])
    claude.assert_called_once_with()
    oc.assert_called_once_with()
    assert out["ok"] is True


def test_currently_enabled() -> None:
    with (
        patch(
            "backend.auth_wizard.claude_statusline.is_installed",
            return_value=True,
        ),
        patch(
            "backend.auth_wizard.opencode_statusline.is_installed",
            return_value=False,
        ),
        patch(
            "backend.auth_wizard.pi_statusline.is_installed",
            return_value=True,
        ),
    ):
        assert auth_wizard.currently_enabled() == ["claude", "pi"]


def test_enable_agents_pi_only() -> None:
    with (
        patch(
            "backend.auth_wizard.pi_statusline.ensure_installed",
        ) as pi,
        patch(
            "backend.auth_wizard.claude_statusline.ensure_installed",
        ) as claude,
    ):
        out = auth_wizard.enable_agents(["pi"])
    pi.assert_called_once_with()
    claude.assert_not_called()
    assert out["ok"] is True
    assert out["agents"]["pi"]["ok"] is True


def test_run_auth_selects_agents(monkeypatch) -> None:
    monkeypatch.setattr(auth_wizard, "_bind_tty", lambda: None)
    monkeypatch.setattr(auth_wizard, "resolve_client_id", lambda: "cid-123")
    monkeypatch.setattr(auth_wizard, "spotify_login", lambda: None)
    monkeypatch.setattr(auth_wizard, "prompt_agents", lambda **_k: ["opencode"])
    with patch(
        "backend.auth_wizard.enable_agents",
        return_value={
            "ok": True,
            "agents": {"opencode": {"ok": True, "action": "installed"}},
        },
    ) as enable:
        out = auth_wizard.run()
    enable.assert_called_once_with(["opencode"])
    assert out["ok"] is True
    assert out["agents"] == ["opencode"]
