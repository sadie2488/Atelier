---
task_id: T01
agent: recommender-engineer
status: done            # done | blocked | failed
---

# REPLY: <task_id>

From: <agent>
To: architect

## Summary

[2–3 sentences: what was built and whether the done-check passed]

## Files changed

- `path` — [what changed]   (every path inside the announcement's allowlist)

## Verification

```
[exact done-check command]
```

```
[actual output, pasted]
```

Scope check:

```
[output of: python3 .claude/scripts/check_scopes.py --diff <task_id>]
```

## Known issues

- [or "None"]

## Not done

- [anything in the goal not completed, or "Nothing"]

## Decisions

- [decisions the architect should record in the registry]

## Needs

- [anything you need from another expert or a human; the architect relays it. Or "None"]
