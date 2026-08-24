import sys

HELP_TEXT = """\
dj — Spotify statusline for Claude Code, OpenCode, and Pi

Commands:
  auth       Spotify login + choose agents to enable
  on         Enable statusline (multi-select agents)
  off        Disable statusline (multi-select agents)
  palette    Show or set artist/song/time colors
  placement  Show or set Pi widget placement (above|below)
  help       Show this help

Examples:
  dj auth
  dj on
  dj off
  dj palette
  dj palette '#888888' '#C1C1C1' '#486E6F'
  dj palette --reset
  dj placement
  dj placement below
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


def _cmd_palette(rest: list[str]) -> None:
    from backend import config
    from backend.opencode import statusline as oc

    if not rest:
        artist, song, time_c = config.load_palette()
        _say(f"artist {artist}")
        _say(f"song   {song}")
        _say(f"time   {time_c}")
        return
    if rest == ["--reset"] or rest == ["-r"]:
        config.clear_palette()
        try:
            oc.write_runtime_config()
        except OSError:
            pass
        artist, song, time_c = config.load_palette()
        _say(f"palette reset → {artist} {song} {time_c}")
        return
    if len(rest) != 3:
        print(
            "usage: dj palette [artist song time] | dj palette --reset",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        triple = config.set_palette(rest)
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    try:
        oc.write_runtime_config()
    except OSError:
        pass
    _say(f"palette {triple[0]} {triple[1]} {triple[2]}")


def _cmd_placement(rest: list[str]) -> None:
    from backend import config
    from backend.pi import statusline as pi

    if not rest:
        _say(config.load_pi_placement())
        return
    if len(rest) != 1:
        print("usage: dj placement [above|below]", file=sys.stderr)
        raise SystemExit(2)
    try:
        value = config.set_pi_placement(rest[0])
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    try:
        pi.write_runtime_config()
    except OSError:
        pass
    _say(value)


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
    if cmd == "palette":
        _cmd_palette(rest)
        return
    if cmd == "placement":
        _cmd_placement(rest)
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
