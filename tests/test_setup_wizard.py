from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_dj.integrate import setup as setup_wizard


def test_device_label() -> None:
    assert (
        setup_wizard.device_label(
            {"id": "1", "name": "MacBook", "type": "Computer", "is_active": True}
        )
        == "MacBook (Computer) · active"
    )
    assert (
        setup_wizard.device_label(
            {"id": "2", "name": "Phone", "type": "Smartphone", "is_active": False}
        )
        == "Phone (Smartphone)"
    )


def test_run_noninteractive_requires_client_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("claude_dj.config.APP_DIR", tmp_path)
    monkeypatch.setattr("claude_dj.config.CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(SystemExit) as exc:
        setup_wizard.run(
            client_id=None,
            device_id=None,
            yes=True,
            force=False,
            skip_claude=True,
            skip_device=True,
        )
    assert exc.value.code == 2


def test_run_noninteractive_full_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("claude_dj.config.APP_DIR", tmp_path)
    monkeypatch.setattr("claude_dj.config.CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("claude_dj.config.DEVICE_PATH", tmp_path / "device.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    devices = [
        {"id": "dev-a", "name": "Mac", "type": "Computer", "is_active": True},
        {"id": "dev-b", "name": "Phone", "type": "Smartphone", "is_active": False},
    ]

    with (
        patch("claude_dj.adapters.spotify.ensure_session") as login,
        patch("claude_dj.adapters.spotify.list_devices", return_value=devices),
        patch("claude_dj.adapters.spotify.save_preferred_device_id") as save_dev,
        patch("claude_dj.adapters.spotify.transfer_playback") as transfer,
        patch("claude_dj.integrate.statusline.ensure_installed", return_value={"ok": True, "action": "installed"}) as sl,
        patch("claude_dj.integrate.claude_code.install_skill", return_value={"ok": True, "action": "installed"}) as skill,
    ):
        out = setup_wizard.run(
            client_id="my-client",
            device_id="dev-b",
            yes=True,
            force=False,
            skip_claude=False,
            skip_device=False,
        )

    login.assert_called_once_with()
    save_dev.assert_called_once_with("dev-b")
    transfer.assert_called_once_with("dev-b", play=False)
    sl.assert_called_once_with()
    skill.assert_called_once_with()
    assert out["ok"] is True
    assert out["spotify_client_id"] == "my-client"
    assert out["device_id"] == "dev-b"
    from claude_dj import config

    assert config.load_app_config()["spotify_client_id"] == "my-client"


def test_run_skip_device_and_claude(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("claude_dj.config.APP_DIR", tmp_path)
    monkeypatch.setattr("claude_dj.config.CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    with (
        patch("claude_dj.adapters.spotify.ensure_session") as login,
        patch("claude_dj.adapters.spotify.list_devices") as list_dev,
        patch("claude_dj.integrate.statusline.ensure_installed") as sl,
        patch("claude_dj.integrate.claude_code.install_skill") as skill,
    ):
        out = setup_wizard.run(
            client_id="cid",
            device_id=None,
            yes=True,
            force=False,
            skip_claude=True,
            skip_device=True,
        )

    login.assert_called_once_with()
    list_dev.assert_not_called()
    sl.assert_not_called()
    skill.assert_not_called()
    assert out["ok"] is True
    assert out.get("device_id") is None


def test_run_unknown_device_id_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("claude_dj.config.APP_DIR", tmp_path)
    monkeypatch.setattr("claude_dj.config.CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    with (
        patch("claude_dj.adapters.spotify.ensure_session"),
        patch(
            "claude_dj.adapters.spotify.list_devices",
            return_value=[{"id": "only", "name": "X", "type": "Computer", "is_active": False}],
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            setup_wizard.run(
                client_id="cid",
                device_id="missing",
                yes=True,
                force=False,
                skip_claude=True,
                skip_device=False,
            )
    assert exc.value.code == 1


def test_prompt_client_id_uses_existing_when_not_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("claude_dj.config.APP_DIR", tmp_path)
    monkeypatch.setattr("claude_dj.config.CONFIG_PATH", tmp_path / "config.json")
    from claude_dj import config

    config.set_spotify_client_id("existing-id")
    # Interactive path mocked: force=False should keep existing without questionary
    got = setup_wizard._resolve_client_id(
        explicit=None,
        force=False,
        interactive=False,
    )
    assert got == "existing-id"
