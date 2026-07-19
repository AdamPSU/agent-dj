---
description: Run Claude DJ lifecycle commands through the installed local CLI.
---

Run the installed Claude DJ CLI.

User command:

/dj `$ARGUMENTS`

Command handling:

- If the command is empty (/dj ``), run `dj status`.
- Otherwise, run `dj $ARGUMENTS`.

Return the command output concisely. Do not add extra explanation unless the command fails.
