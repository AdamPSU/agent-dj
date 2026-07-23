from unittest.mock import patch

from backend.claude import auth as auth_mod


def test_run_client_id_login_statusline(monkeypatch) -> None:
    monkeypatch.setattr(auth_mod, "_bind_tty", lambda: None)
    monkeypatch.setattr(auth_mod, "_resolve_client_id", lambda: "cid-123")
    monkeypatch.setattr(auth_mod, "_spotify_login", lambda: None)
    with patch.object(
        auth_mod.statusline,
        "ensure_installed",
        return_value={"ok": True, "action": "installed"},
    ) as inst:
        out = auth_mod.run()
    inst.assert_called_once_with()
    assert out["ok"] is True
    assert out["spotify_client_id"] == "cid-123"
