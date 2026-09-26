#!/usr/bin/env python3
"""
Documentation consistency check.

This project's rules live across several files — agent definitions, lane contexts,
DECISIONS.md, the scope guard, and the frontend API doc. They can drift apart, and when
they do an agent follows one and violates another without anyone noticing.

Run this after ANY change to the docs, and in the PM's push gate.

    python tools/check_docs.py
    python tools/check_docs.py --root .

Exit 0 = consistent, 1 = contradictions found.
Standard library only.
"""

import argparse
import os
import re
import sys

CATEGORIES = {"tops", "bottoms", "jackets"}
GARMENT_TYPES = {"shirt", "dress", "pants", "skirt", "shorts", "jacket", "coat"}
LANES = ["vision", "styling", "avatar"]


class Check:
    def __init__(self):
        self.problems = []
        self.notes = []

    def fail(self, where, msg):
        self.problems.append((where, msg))

    def note(self, msg):
        self.notes.append(msg)


def read(root, *parts):
    path = os.path.join(root, *parts)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def check_files_exist(root, c):
    required = [
        ("contract/DECISIONS.md", "resolved values every lane reads"),
        ("contract/colors.json", "the shared color table"),
        ("contract/OPEN_QUESTIONS.md", "lanes cannot ask the PM without it"),
        ("ARCHITECTURE.md", "shared entry point"),
        ("coordination/BACKEND_API.md", "what the frontend builds against"),
        ("coordination/FRONTEND_REQUESTS.md", "how the frontend reports blockers"),
        (".claude/hooks/scope_guard.py", "lane rules are advisory without it"),
    ]
    for rel, why in required:
        if not os.path.exists(os.path.join(root, rel)):
            c.fail(rel, f"missing - {why}")

    for lane in LANES:
        for rel in (f".claude/agents/{lane}.md", f"backend/{lane}/CLAUDE.md"):
            if not os.path.exists(os.path.join(root, rel)):
                c.fail(rel, "missing")


def check_tools_exist(root, c):
    """Every tool an agent is told to run must exist, or the agent burns turns finding out."""
    pattern = re.compile(r"python\s+(tools/[A-Za-z0-9_./-]+\.py)")
    referenced = {}
    for lane in LANES:
        for rel in (f".claude/agents/{lane}.md", f"backend/{lane}/CLAUDE.md"):
            text = read(root, rel)
            if not text:
                continue
            for m in pattern.finditer(text):
                referenced.setdefault(m.group(1), set()).add(rel)

    for tool, sources in sorted(referenced.items()):
        if not os.path.exists(os.path.join(root, tool)):
            c.fail(tool, f"referenced by {', '.join(sorted(sources))} but does not exist")


def check_scope_alignment(root, c):
    """Agent scope lists must match scope_guard's LANE_SCOPE, or agents get blocked
    doing what they were told to do."""
    guard = read(root, ".claude/hooks/scope_guard.py")
    if not guard:
        return

    block = re.search(r"LANE_SCOPE\s*=\s*\{(.*?)\n\}", guard, re.S)
    if not block:
        c.fail("scope_guard.py", "could not parse LANE_SCOPE")
        return

    guard_scope = {}
    for lane_m in re.finditer(r'"(\w+)"\s*:\s*\[(.*?)\]', block.group(1), re.S):
        guard_scope[lane_m.group(1)] = set(re.findall(r'"([^"]+)"', lane_m.group(2)))

    for lane in LANES:
        text = read(root, f".claude/agents/{lane}.md")
        if not text:
            continue
        fence = re.search(r"## Scope.*?```(.*?)```", text, re.S)
        if not fence:
            c.fail(f".claude/agents/{lane}.md", "no scope code block found")
            continue
        declared = {l.strip() for l in fence.group(1).splitlines() if l.strip()}
        guarded = guard_scope.get(lane, set())

        for p in declared - guarded:
            c.fail(f"{lane}", f"agent claims '{p}' but scope_guard does not allow it - "
                              f"the agent will be blocked doing its own task")
        for p in guarded - declared:
            c.fail(f"{lane}", f"scope_guard allows '{p}' but the agent file does not "
                              f"mention it - unenforced permission")


def check_escape_hatches(root, c):
    """Agents are told to append to OPEN_QUESTIONS.md and run request_dep.py. If the
    guard freezes those paths without an exception, both instructions are dead."""
    guard = read(root, ".claude/hooks/scope_guard.py")
    if not guard:
        return
    block = re.search(r"SHARED_WRITABLE\s*=\s*\[(.*?)\]", guard, re.S)
    allowed = set(re.findall(r'"([^"]+)"', block.group(1))) if block else set()

    frozen = re.search(r"FROZEN\s*=\s*\[(.*?)\]", guard, re.S)
    frozen_pats = set(re.findall(r'"([^"]+)"', frozen.group(1))) if frozen else set()

    if "contract/**" in frozen_pats:
        if "contract/OPEN_QUESTIONS.md" not in allowed:
            c.fail("scope_guard.py",
                   "contract/** is frozen but OPEN_QUESTIONS.md is not in SHARED_WRITABLE - "
                   "agents are told to append there and will be blocked")
        if "contract/DEP_REQUESTS.jsonl" not in allowed:
            c.fail("scope_guard.py",
                   "contract/** is frozen but DEP_REQUESTS.jsonl is not in SHARED_WRITABLE - "
                   "request_dep.py will fail for every lane")


def check_dress_consistency(root, c):
    """The dress rule changed late and is the likeliest thing to be stale somewhere."""
    stale = [
        (r"dress(?:es)?\s+(?:never|cannot|does not)\s+pair", "says dresses cannot pair with a bottom"),
        (r"dress\s+excludes\s+(?:top|bottom)", "says a dress excludes top+bottom"),
        (r"category:\s*dress", "treats dress as a category (it is a garment_type)"),
        (r"\btop\s*\+\s*bottom,?\s*or\s*(?:a\s*)?dress\b", "uses the old two-shape outfit model"),
    ]
    targets = ["contract/DECISIONS.md", "ARCHITECTURE.md", "PM_TASKS.md",
               "coordination/BACKEND_API.md"]
    for lane in LANES:
        targets += [f".claude/agents/{lane}.md", f"backend/{lane}/CLAUDE.md"]

    for rel in targets:
        text = read(root, rel)
        if not text:
            continue
        for pat, msg in stale:
            for m in re.finditer(pat, text, re.I):
                line = text[:m.start()].count("\n") + 1
                c.fail(f"{rel}:{line}", f"stale dress rule - {msg}")


def check_category_lists(root, c):
    """A doc listing categories must list exactly tops/bottoms/jackets."""
    pattern = re.compile(r"\(\s*tops\s*\|[^)]*\)")
    targets = ["contract/DECISIONS.md", "coordination/BACKEND_API.md", "ARCHITECTURE.md"]
    for lane in LANES:
        targets += [f".claude/agents/{lane}.md", f"backend/{lane}/CLAUDE.md"]

    for rel in targets:
        text = read(root, rel)
        if not text:
            continue
        for m in pattern.finditer(text):
            listed = {t.strip() for t in m.group(0).strip("()").split("|")}
            if "dress" in listed:
                line = text[:m.start()].count("\n") + 1
                c.fail(f"{rel}:{line}",
                       "dress listed as a category - it is a garment_type under tops")
            elif listed != CATEGORIES:
                line = text[:m.start()].count("\n") + 1
                c.fail(f"{rel}:{line}",
                       f"category list is {sorted(listed)}, expected {sorted(CATEGORIES)}")


def check_colors(root, c):
    """colors.json must parse, must not carry is_neutral, and its everyday neutrals
    must match what the lane docs promise."""
    import json
    raw = read(root, "contract/colors.json")
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        c.fail("contract/colors.json", f"invalid JSON: {e}")
        return

    colors = data.get("colors", [])
    if not colors:
        c.fail("contract/colors.json", "no colors defined")
        return

    names = set()
    for entry in colors:
        name = entry.get("name")
        if name in names:
            c.fail("contract/colors.json", f"duplicate color name '{name}'")
        names.add(name)
        if "is_neutral" in entry:
            c.fail("contract/colors.json",
                   f"'{name}' carries is_neutral - that is computed from chroma, "
                   f"never read from this table")
        lab = entry.get("lab")
        if not (isinstance(lab, list) and len(lab) == 3):
            c.fail("contract/colors.json", f"'{name}' has a malformed lab value")

    everyday = {e["name"] for e in colors if e.get("everyday_neutral")}
    expected = {"navy", "denim", "beige", "brown", "camel", "olive"}
    if everyday != expected:
        c.fail("contract/colors.json",
               f"everyday neutrals are {sorted(everyday)}, docs promise {sorted(expected)}")

    for alias, target in data.get("retail_aliases", {}).items():
        if alias.startswith("_"):
            continue
        if target not in names:
            c.fail("contract/colors.json",
                   f"alias '{alias}' maps to '{target}', which is not a defined color")


def check_git_rule(root, c):
    """Every agent must carry the no-git rule; it is what keeps one committer."""
    for lane in LANES:
        text = read(root, f".claude/agents/{lane}.md")
        if text and "Never run git" not in text:
            c.fail(f".claude/agents/{lane}.md", "missing the 'Never run git' rule")


def check_render_contract(root, c):
    """The polling contract must describe the same states on both sides."""
    api = read(root, "coordination/BACKEND_API.md")
    if not api:
        return
    for token in ("render_id", "pending", "done", "failed", "local_url", "generated_url"):
        if token not in api:
            c.fail("coordination/BACKEND_API.md",
                   f"render polling contract does not mention '{token}'")

    avatar = read(root, ".claude/agents/avatar.md")
    if avatar and "render_id" not in avatar:
        c.fail(".claude/agents/avatar.md",
               "does not mention render_id - it implements the polling contract")


def main():
    p = argparse.ArgumentParser(description="Check project docs for contradictions.")
    p.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = p.parse_args()
    root = os.path.abspath(args.root)

    c = Check()
    for fn in (check_files_exist, check_tools_exist, check_scope_alignment,
               check_escape_hatches, check_dress_consistency, check_category_lists,
               check_colors, check_git_rule, check_render_contract):
        try:
            fn(root, c)
        except Exception as e:
            c.fail(fn.__name__, f"check itself errored: {e}")

    print(f"check_docs: scanning {root}\n")
    if c.notes:
        for n in c.notes:
            print(f"  note: {n}")
        print()

    if not c.problems:
        print("check_docs: PASS - no contradictions found.")
        return 0

    print(f"check_docs: FAIL - {len(c.problems)} contradiction(s)\n")
    for where, msg in c.problems:
        print(f"  {where}\n      {msg}")
    print("\nFix these before dispatching. An agent that follows one document and "
          "violates another\nwill not notice, and neither will you until integration.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
