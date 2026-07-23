import sys

HELP_TEXT = """\
dj — Spotify statusline for Claude Code and OpenCode

Commands:
  auth    Spotify login + choose agents to enable
  on      Enable statusline (multi-select agents)
  off     Disable statusline (multi-select agents)
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
    from backend import auth_wizard

    auth_wizard.run()


def _cmd_on() -> None:
    from backend import auth_wizard

    auth_wizard.run_on()


def _cmd_off() -> None:
    from backend import auth_wizard

    auth_wizard.run_off()


def _cmd_tick(*, as_json: bool = False) -> None:
    from backend.claude import statusline

    rendered = statusline.tick(as_json=as_json)
    if rendered:
        sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("help", "-h", "--help"):
        _cmd_help()
        return

    cmd, rest = argv[0], argv[1:]

    if cmd == "auth":
        if rest:
            print(f"unknown command: {cmd} {' '.join(rest)}", file=sys.stderr)
            _cmd_help()
            raise SystemExit(2)
        _cmd_auth()
        return
    if cmd == "on":
        if rest:
            print(f"unknown command: {cmd} {' '.join(rest)}", file=sys.stderr)
            _cmd_help()
            raise SystemExit(2)
        _cmd_on()
        return
    if cmd == "off":
        if rest:
            print(f"unknown command: {cmd} {' '.join(rest)}", file=sys.stderr)
            _cmd_help()
            raise SystemExit(2)
        _cmd_off()
        return
    if cmd == "tick":
        as_json = False
        for arg in rest:
            if arg in ("--json", "-j"):
                as_json = True
            else:
                print(f"unknown command: tick {arg}", file=sys.stderr)
                _cmd_help()
                raise SystemExit(2)
        _cmd_tick(as_json=as_json)
        return

    print(f"unknown command: {cmd}", file=sys.stderr)
    _cmd_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
