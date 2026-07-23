import sys

HELP_TEXT = """\
dj — Spotify statusline for Claude Code

Commands:
  auth    Spotify login + enable statusline
  on      Enable statusline
  off     Disable statusline
  help    Show this help

Examples:
  dj auth
  dj on
  dj off
"""


def _say(msg: str) -> None:
    sys.stdout.write(msg if msg.endswith("\n") else msg + "\n")


def _cmd_help() -> None:
    sys.stdout.write(HELP_TEXT)


def _cmd_auth() -> None:
    from backend.claude import auth as auth_wizard

    auth_wizard.run()


def _cmd_on() -> None:
    from backend.claude import statusline

    out = statusline.ensure_installed()
    if not out.get("ok"):
        print(out.get("error") or "failed to enable statusline", file=sys.stderr)
        raise SystemExit(1)
    action = out.get("action") or "enabled"
    _say(f"statusline {action}.")


def _cmd_off() -> None:
    from backend.claude import statusline

    out = statusline.uninstall()
    if not out.get("ok"):
        print(out.get("error") or "failed to disable statusline", file=sys.stderr)
        raise SystemExit(1)
    action = out.get("action") or "disabled"
    if action == "noop":
        _say("statusline already off.")
    else:
        _say("statusline off.")


def _cmd_tick() -> None:
    from backend.claude import statusline

    rendered = statusline.tick()
    if rendered:
        sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("help", "-h", "--help"):
        _cmd_help()
        return

    cmd, rest = argv[0], argv[1:]
    if rest:
        print(f"unknown command: {cmd} {' '.join(rest)}", file=sys.stderr)
        _cmd_help()
        raise SystemExit(2)

    if cmd == "auth":
        _cmd_auth()
        return
    if cmd == "on":
        _cmd_on()
        return
    if cmd == "off":
        _cmd_off()
        return
    if cmd == "tick":
        _cmd_tick()
        return

    print(f"unknown command: {cmd}", file=sys.stderr)
    _cmd_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
