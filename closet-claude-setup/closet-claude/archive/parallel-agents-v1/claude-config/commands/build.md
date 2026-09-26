---
description: Tell the architect what to build - it plans scoped tasks, waits for your go, then announces and dispatches them
argument-hint: <what to build>
---

# Build

Follow the `architect` skill for: **$ARGUMENTS**

1. **Plan** the work as tasks that each fit one expert's scope, reusing `TASKS.md` IDs where they match. Show the plan table and stop until the human says "go".
2. **Announce** each approved task with `announce.py`, filling in all architect context first.
3. **Dispatch** experts as `announce.py` prints (cwd pinned, in the background; at most 2 at once, only tasks the scope check allows together).
4. **Collect** each finished task with `/collect <id>`, relay any **Needs** as new announcements, and **review** it.
5. **Report** results and the manual merge commands to the human.
