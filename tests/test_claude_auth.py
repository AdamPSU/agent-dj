from unittest.mock import patch

from backend.claude import auth as auth_mod


def test_run_delegates_to_auth_wizard() -> None:
    with patch("backend.auth_wizard.run", return_value={"ok": True}) as run:
        out = auth_mod.run()
    run.assert_called_once_with()
    assert out["ok"] is True
