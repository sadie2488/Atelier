#!/usr/bin/env python3
"""Claude Code hook (async): log every agent action to Postgres. Human-owned.
Runs with "async": true, so it never slows or blocks an agent. Blocking is guard.py's job.

Reads the hook JSON from stdin and inserts one row into agent_actions.
- DB: $AGENT_LOG_DATABASE_URL (never commit it). If unset or unreachable, the row
  goes to .claude/logs/actions.jsonl with the error; replay later with --replay.
- Secrets are redacted and large payloads truncated before anything is stored.
- Stage 1 (no AGENT_LOG_DATABASE_URL): everything queues to .claude/logs/actions.jsonl.
  Stage 2: set the URL, then run --replay once. After a DB failure it queues for 60 s.
"""
import datetime, getpass, json, os, re, socket, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
FALLBACK = ROOT / ".claude" / "logs" / "actions.jsonl"
BACKOFF = ROOT / ".claude" / "logs" / "db_backoff_until"
BACKOFF_SECONDS = 60
DB_URL = os.environ.get("AGENT_LOG_DATABASE_URL")
MAX_STR = 2000
WT_RE = re.compile(r"closet-wt/([^/]+)/")

SECRETS = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b(postgres(?:ql)?|mongodb(?:\+srv)?|redis)://\S+"), r"\1://[REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|auth)\b(\s*[=:]\s*)([\"']?)[^\s\"',;]+"), r"\1\2\3[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
]
FILE_EDIT = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
FILE_READ = {"Read", "Grep", "Glob", "LS", "NotebookRead"}

COLUMNS = ["ts", "session_id", "agent_id", "agent_type", "event", "tool_name", "action_kind",
           "target", "http_method", "task_id", "git_branch", "cwd", "in_scope", "success",
           "host", "user_name", "payload"]


def redact(s):
    for rx, rep in SECRETS:
        s = rx.sub(rep, s)
    return s


def clean(obj):
    """Redact and truncate every string in a JSON-like structure."""
    if isinstance(obj, str):
        s = redact(obj)
        return s if len(s) <= MAX_STR else s[:MAX_STR] + f"...[truncated {len(s) - MAX_STR} chars]"
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj[:50]]
    return obj


def is_env_file(path):
    return bool(path) and (path.endswith(".env") or "/.env" in path) and not path.endswith(".env.example")


def classify(name, ti):
    """Return (action_kind, target, http_method)."""
    if not name:
        return None, None, None
    if name in FILE_EDIT:
        return "file_edit", ti.get("file_path") or ti.get("notebook_path"), None
    if name in FILE_READ:
        return "file_read", ti.get("file_path") or ti.get("path") or ti.get("pattern"), None
    if name == "Bash":
        cmd = ti.get("command", "") or ""
        m = re.search(r"(?:-X|--request)\s*([A-Za-z]+)", cmd)
        method = m.group(1).upper() if m else None
        if not method and "curl" in cmd and re.search(r"(--data|--json|\s-d\s|\s-F\s)", cmd):
            method = "POST"
        posting = (method in {"POST", "PUT", "PATCH", "DELETE"}
                   or re.search(r"\bgit\s+push\b|\bgh\s+(pr|issue|release)\s+(create|comment|edit|merge)\b", cmd))
        network = re.search(r"\b(curl|wget|gh|vercel|doctl|httpie|http)\b", cmd)
        kind = "post" if posting else "network_command" if network else "command"
        return kind, redact(cmd)[:300], method
    if name in {"WebFetch", "WebSearch"}:
        return "web", ti.get("url") or ti.get("query"), "GET" if name == "WebFetch" else None
    if name in {"Task", "Agent"}:
        return "dispatch", f"{ti.get('subagent_type')}: {ti.get('description', '')}"[:300], None
    if name == "TodoWrite":
        return "todo", None, None
    if name.startswith("mcp__"):
        browserish = re.search(r"chrome|playwright|browser|puppeteer", name, re.I)
        return ("browser" if browserish else "mcp"), name, None
    return "other", None, None


def task_and_rel(path):
    """(task_id, repo-relative path, worktree root) for paths inside ../closet-wt/<ID>/."""
    if not path:
        return None, None, None
    p = path.replace("\\", "/")
    m = WT_RE.search(p)
    return (m.group(1), p[m.end():], Path(p[:m.end()])) if m else (None, None, None)


def announced_agent(wt_root, task):
    """Agent named in the task's ANNOUNCEMENT.md front matter, if any."""
    try:
        text = (wt_root / ".claude" / "tasks" / task / "ANNOUNCEMENT.md").read_text()
        m = re.search(r"^agent:\s*(\S+)", text.split("\n---", 2)[0], re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def scope_check(task, rel, wt_root):
    """True/False for a file edit inside a task worktree; None if unknown."""
    if not task or rel is None:
        return None
    if rel.startswith(".claude/tasks/"):
        base = f".claude/tasks/{task}/"
        return rel.startswith(base) and (rel[len(base):] == "REPLY.md" or rel[len(base):].startswith("evidence/"))
    try:
        cfg = json.loads((ROOT / ".claude" / "scopes.json").read_text())
    except Exception:
        return None
    agent = AGENT_TYPE or announced_agent(wt_root, task) or cfg["task_agents"].get(task)
    if not agent:
        return None
    if any(rel.startswith(h) for h in cfg["human_only"]):
        return False
    if any(rel.startswith(s) for s in cfg["shared_append_only"]):
        return True
    return any(rel.startswith(s) for s in cfg["agents"].get(agent, []))


def git_branch(cwd):
    try:
        return subprocess.run(["git", "-C", cwd or ".", "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=1).stdout.strip() or None
    except Exception:
        return None


def success_of(resp):
    if isinstance(resp, dict):
        if resp.get("success") is False or resp.get("is_error") or resp.get("error"):
            return False
        if "success" in resp:
            return bool(resp["success"])
    return None


AGENT_TYPE = None


def build_row(d):
    global AGENT_TYPE
    AGENT_TYPE = d.get("agent_type")
    event = d.get("hook_event_name", "unknown")
    name = d.get("tool_name")
    ti = d.get("tool_input") or {}
    kind, target, method = classify(name, ti)
    if event in {"SessionStart", "SessionEnd", "Stop", "SubagentStop"}:
        kind = "lifecycle"
    if event == "UserPromptSubmit":
        kind = "prompt"

    payload = {"tool_input": ti}
    if event == "PostToolUse":
        payload["tool_response"] = d.get("tool_response")
    if event == "UserPromptSubmit":
        payload = {"prompt": d.get("prompt")}
    if event in {"SessionStart", "SessionEnd", "Stop", "SubagentStop"}:
        payload = {k: v for k, v in d.items() if k not in {"session_id", "transcript_path", "cwd"}}
    if is_env_file(target if isinstance(target, str) else None):
        payload = {"redacted": "env file contents never logged"}

    path_for_task = target if kind in {"file_edit", "file_read"} else d.get("cwd")
    task, rel, wt_root = task_and_rel(path_for_task)
    in_scope = scope_check(task, rel, wt_root) if kind == "file_edit" else None

    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": d.get("session_id") or "unknown",
        "agent_id": d.get("agent_id"),
        "agent_type": d.get("agent_type") or d.get("subagent_type"),
        "event": event,
        "tool_name": name,
        "action_kind": kind,
        "target": redact(str(target))[:500] if target else None,
        "http_method": method,
        "task_id": task,
        "git_branch": git_branch(d.get("cwd")),
        "cwd": d.get("cwd"),
        "in_scope": in_scope,
        "success": success_of(d.get("tool_response")) if event == "PostToolUse" else None,
        "host": socket.gethostname(),
        "user_name": getpass.getuser(),
        "payload": clean(payload),
    }


def insert(rows):
    import psycopg
    from psycopg.types.json import Jsonb
    sql = f"INSERT INTO agent_actions ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})"
    with psycopg.connect(DB_URL, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(sql, [Jsonb(r[c]) if c == "payload" else r[c] for c in COLUMNS])


def fallback(row, err):
    FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    row = dict(row, log_error=err[:300])
    with FALLBACK.open("a") as f:
        f.write(json.dumps(row) + "\n")


def replay():
    if not FALLBACK.exists():
        print("nothing to replay")
        return 0
    rows = [json.loads(l) for l in FALLBACK.read_text().splitlines() if l.strip()]
    for r in rows:
        r.pop("log_error", None)
    insert(rows)
    FALLBACK.unlink()
    print(f"replayed {len(rows)} rows")
    return 0


def main():
    if "--replay" in sys.argv:
        return replay()
    try:
        d = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        row = build_row(d)
    except Exception as e:
        fallback({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "session_id": str(d.get("session_id")), "event": str(d.get("hook_event_name"))},
                 f"build_row failed: {e!r}")
        return 0
    try:
        if not DB_URL:
            raise RuntimeError("AGENT_LOG_DATABASE_URL not set (stage 1: queued locally)")
        if BACKOFF.exists() and float(BACKOFF.read_text() or 0) > datetime.datetime.now().timestamp():
            raise RuntimeError("database backoff active")
        insert([row])
    except Exception as e:
        fallback(row, repr(e))
        if DB_URL and "backoff" not in repr(e):
            BACKOFF.parent.mkdir(parents=True, exist_ok=True)
            BACKOFF.write_text(str(datetime.datetime.now().timestamp() + BACKOFF_SECONDS))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
