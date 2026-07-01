---
description: Run Claude DJ lifecycle commands through the local Python CLI.
---

Run the Claude DJ CLI from the project root.

User command: 

/dj `$ARGUMENTS$` 

Command handling:

- If the command is empty (/dj ``), run `uv run claude-dj status`.
- Otherwise, run `uv run claude-dj $ARGUMENTS`.

Return the command output concisely. Do not add extra explanation unless the command fails.
