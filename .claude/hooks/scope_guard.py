#!/usr/bin/env python3
"""
Scope guard for Atelier's backend lane subagents.

Wire as a PreToolUse hook in .claude/settings.json matching Write, Edit, and Bash.
Blocks three classes of mistake before they land:

  1. A lane writing outside the files it owns
  2. Any subagent running git
  3. Any subagent editing requirements.txt, main.py, or the frozen contract

Reads the hook payload on stdin. Exit 0 allows; exit 2 blocks and returns the reason to
the agent so it can self-correct.

The PM (no ATELIER_LANE set) is unrestricted by design.
"""

import json
import os
import re
import sys
from fnmatch import fnmatch

# Repo root: this file lives at <root>/.claude/hooks/scope_guard.py
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# Lane -> glob patterns that lane may write.
LANE_SCOPE = {
    "vision": [
        "backend/vision/**",
        "backend/routes/items.py",
        "backend/tests/test_vision.py",
        "media/_failures/**",
    ],
    "styling": [
        "backend/styling/**",
        "backend/routes/outfits.py",
        "backend/tests/test_styling.py",
    ],
    "avatar": [
        "backend/avatar/**",
        "backend/routes/avatar.py",
        "backend/tests/test_avatar.py",
        "media/_preview/**",
    ],
}

# Writable by ANY lane, overriding FROZEN below. These are the escape hatches the agent
# instructions depend on: without them, "stop and ask the PM" is itself blocked.
SHARED_WRITABLE = [
    "contract/OPEN_QUESTIONS.md",
    "contract/DEP_REQUESTS.jsonl",
]

# Never writable by a subagent, even inside its own scope.
FROZEN = [
    "contract/**",
    "requirements.txt",
    "backend/requirements.txt",
    "backend/main.py",
    "backend/db.py",
    "backend/config.py",
    "backend/tests/conftest.py",
    ".claude/**",
    "tools/**",
    "coordination/**",
    "fixtures/golden/**",
]

GIT_CALL = re.compile(r"(^|[;&|]\s*)git(\s|$)", re.IGNORECASE)


def normalize(path: str) -> str:
    """Return a repo-relative POSIX path.

    Claude Code usually passes absolute paths, so a naive lstrip('./') would turn
    '/home/u/repo/backend/vision/x.py' into 'home/u/repo/backend/vision/x.py' and match
    nothing — silently allowing every write. Resolve against the repo root instead.
    """
    path = path.replace("\\", "/")
    if os.path.isabs(path):
        try:
            path = os.path.relpath(os.path.abspath(path), REPO_ROOT)
        except ValueError:
            # Different drive on Windows: not in the repo, so treat it as out of scope.
            return path.lstrip("/")
        path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def matches(path: str, patterns) -> bool:
    """True if path matches any pattern.

    fnmatch's '*' spans '/', so 'backend/vision/**' matches nested files. A bare
    directory pattern also matches the directory's own path.
    """
    for p in patterns:
        if fnmatch(path, p):
            return True
        if p.endswith("/**") and path == p[:-3]:
            return True
    return False


LANE_LINE = re.compile(r"ATELIER_LANE=([a-z]+)", re.IGNORECASE)


def resolve_lane(payload: dict) -> str:
    """Which lane is making this tool call?

    1. ATELIER_LANE in the environment (a lane running as its own session).
    2. agent_type, when the subagent was launched as a .claude/agents/<lane>.md type.
    3. A subagent (agent_id set) whose dispatch prompt starts with ATELIER_LANE=<lane>.
       Subagents share the PM's environment, so the prompt is the only per-lane signal;
       the subagent cannot rewrite its own first transcript line.
    Returns "" for the PM (no agent_id) or a subagent dispatched without a lane.
    """
    lane = os.environ.get("ATELIER_LANE", "").strip().lower()
    if lane:
        return lane
    agent_type = (payload.get("agent_type") or "").strip().lower()
    if agent_type in LANE_SCOPE:
        return agent_type
    agent_id = payload.get("agent_id")
    transcript = payload.get("transcript_path") or ""
    if not agent_id or not transcript:
        return ""
    sub = os.path.join(os.path.splitext(transcript)[0], "subagents", f"agent-{agent_id}.jsonl")
    try:
        with open(sub, encoding="utf-8") as f:
            first = json.loads(f.readline())
    except (OSError, ValueError):
        return ""
    content = (first.get("message") or {}).get("content", "")
    if not isinstance(content, str):
        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    head = content.strip().splitlines()[0] if content.strip() else ""
    m = LANE_LINE.match(head.strip())
    return m.group(1).lower() if m else ""


def deny(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # Malformed payload: fail open rather than wedging the session.

    lane = resolve_lane(payload)
    if not lane:
        sys.exit(0)  # PM session: unrestricted by design.

    if lane not in LANE_SCOPE:
        deny(
            f"Unknown lane '{lane}'. The PM must set ATELIER_LANE to one of: "
            f"{', '.join(sorted(LANE_SCOPE))}."
        )

    tool = payload.get("tool_name", "")
    params = payload.get("tool_input", {}) or {}

    # --- Bash: block git outright -------------------------------------------
    if tool == "Bash":
        command = params.get("command", "")
        if GIT_CALL.search(command):
            deny(
                "BLOCKED: subagents may not run git. The PM is the only committer.\n"
                "Finish your task, leave your files in the working tree, and report "
                "completion to the PM. It will stage and commit your lane."
            )
        sys.exit(0)

    # --- Write / Edit: enforce ownership ------------------------------------
    target = params.get("file_path") or params.get("path") or ""
    if not target:
        sys.exit(0)

    norm = normalize(target)

    # Escape hatches win over FROZEN.
    if matches(norm, SHARED_WRITABLE):
        sys.exit(0)

    if matches(norm, FROZEN):
        deny(
            f"BLOCKED: '{norm}' is PM-owned and frozen to subagents.\n"
            "If this genuinely needs to change, stop and report to the PM with the file "
            "and the reason.\n"
            "  - A missing value?      append to contract/OPEN_QUESTIONS.md\n"
            f"  - A dependency?         python tools/request_dep.py <package> --lane {lane} "
            f'--reason "..."'
        )

    if not matches(norm, LANE_SCOPE[lane]):
        owned = "\n  ".join(LANE_SCOPE[lane])
        deny(
            f"BLOCKED: '{norm}' is outside the {lane} lane.\n"
            f"You may edit only:\n  {owned}\n"
            "Report the needed change to the PM instead of working around this."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
