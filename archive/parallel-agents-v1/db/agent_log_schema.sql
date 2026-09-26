-- Agent action log + app API call log. Human-owned. Run once against the log database.
-- Works on plain Postgres; becomes TimescaleDB hypertables automatically if the extension exists.

CREATE TABLE IF NOT EXISTS agent_actions (
  id           bigserial,
  ts           timestamptz NOT NULL DEFAULT now(),
  session_id   text        NOT NULL,          -- Claude Code session id (main session; subagents share it)
  agent_id     text,                          -- subagent id, when Claude Code provides it
  agent_type   text,                          -- subagent name, when Claude Code provides it
  event        text        NOT NULL,          -- SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, SubagentStop, Stop, SessionEnd
  tool_name    text,
  action_kind  text,                          -- file_edit, file_read, command, network_command, post, web, mcp, browser, dispatch, prompt, lifecycle, other
  target       text,                          -- file path, URL, command (truncated), or tool name
  http_method  text,
  task_id      text,                          -- from the worktree path ../closet-wt/<ID>/
  git_branch   text,
  cwd          text,
  in_scope     boolean,                       -- file edits only: inside the task's agent scope?
  success      boolean,
  host         text,
  user_name    text,
  payload      jsonb,                         -- redacted, truncated tool input/response
  PRIMARY KEY (id, ts)
);

CREATE INDEX IF NOT EXISTS agent_actions_ts      ON agent_actions (ts DESC);
CREATE INDEX IF NOT EXISTS agent_actions_session ON agent_actions (session_id, ts DESC);
CREATE INDEX IF NOT EXISTS agent_actions_task    ON agent_actions (task_id, ts DESC);
CREATE INDEX IF NOT EXISTS agent_actions_kind    ON agent_actions (action_kind, ts DESC);

CREATE TABLE IF NOT EXISTS app_api_calls (
  id          bigserial,
  ts          timestamptz NOT NULL DEFAULT now(),
  service     text NOT NULL,                  -- 'gemini'
  method      text NOT NULL,                  -- classify | rerank | generate_head
  model       text,
  latency_ms  integer,
  status      text NOT NULL,                  -- ok | error | timeout | schema_error
  cache_hit   boolean,
  input_hash  text,
  error       text,
  PRIMARY KEY (id, ts)
);
CREATE INDEX IF NOT EXISTS app_api_calls_ts ON app_api_calls (ts DESC);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    PERFORM create_hypertable('agent_actions', 'ts', if_not_exists => TRUE);
    PERFORM create_hypertable('app_api_calls', 'ts', if_not_exists => TRUE);
  END IF;
END $$;

-- File edits outside the editing agent's scope
CREATE OR REPLACE VIEW scope_violations AS
SELECT ts, session_id, task_id, agent_type, target
FROM agent_actions
WHERE action_kind = 'file_edit' AND in_scope IS FALSE
ORDER BY ts DESC;

-- Anything that left the machine: posts, network commands, web fetches, MCP and browser calls
CREATE OR REPLACE VIEW external_actions AS
SELECT ts, session_id, task_id, agent_type, action_kind, http_method, target
FROM agent_actions
WHERE event = 'PostToolUse' AND action_kind IN ('post', 'network_command', 'web', 'mcp', 'browser')
ORDER BY ts DESC;

-- One row per session
CREATE OR REPLACE VIEW session_summary AS
SELECT session_id,
       min(ts) AS started,
       max(ts) AS last_action,
       count(*) AS actions,
       count(*) FILTER (WHERE action_kind = 'file_edit' AND event = 'PostToolUse') AS file_edits,
       count(*) FILTER (WHERE action_kind IN ('post','network_command','web','mcp','browser') AND event = 'PostToolUse') AS external_calls,
       count(*) FILTER (WHERE in_scope IS FALSE) AS scope_violations,
       array_agg(DISTINCT task_id) FILTER (WHERE task_id IS NOT NULL) AS tasks
FROM agent_actions
GROUP BY session_id;
