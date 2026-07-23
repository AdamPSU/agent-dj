"""Minimal firecrawl-style wizard chrome (Spotify green only)."""

from __future__ import annotations

import sys

from rich.console import Console

# Spotify brand green — sole accent color in the wizard.
GREEN = "#1DB954"

console = Console(stderr=True)


def header(title: str, *, emoji: str = "🎵") -> None:
    console.print()
    console.print(f"  {emoji} [{GREEN}]{title}[/{GREEN}]")
    console.print()


def ok(message: str) -> None:
    console.print(f"  [{GREEN}]✓[/{GREEN}] {message}")


def fail(message: str) -> None:
    console.print(f"  ✗ {message}")


def dim(message: str) -> None:
    console.print(f"  [dim]{message}[/dim]")


def blank() -> None:
    console.print()


def answered(question: str, answer: str) -> None:
    """Echo a completed prompt the way inquirer/firecrawl does."""
    console.print(f"[{GREEN}]✔[/{GREEN}] {question} [dim]{answer}[/dim]")


def confirm_step(question: str, *, default_yes: bool = True) -> bool:
    from beaupy import Config, confirm

    Config.raise_on_interrupt = True
    try:
        yes = bool(
            confirm(
                question,
                default_is_yes=default_yes,
                cursor_style=GREEN,
            )
        )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("cancelled") from None
    answered(question, "Yes" if yes else "No")
    return yes


def prompt_step(
    question: str,
    *,
    initial: str = "",
    secret: bool = False,
) -> str:
    from beaupy import Config, prompt

    Config.raise_on_interrupt = True
    try:
        value = prompt(
            question,
            initial_value=initial,
            validator=lambda s: bool(str(s).strip()),
            secure=secret,
        )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit("cancelled") from None
    if value is None:
        raise SystemExit("cancelled")
    text = str(value).strip()
    display = ("*" * min(8, len(text))) if secret else text
    if len(display) > 48:
        display = display[:45] + "…"
    answered(question, display)
    return text
