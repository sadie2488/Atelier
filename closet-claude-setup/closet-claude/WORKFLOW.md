# WORKFLOW.md — two people, two agents (humans)

Each person runs **one** Claude Code session on their own laptop and works down their lane in `TASKS.md`. Parallelism comes from the two of you working in separate folders, not from extra agents.

```
            GitHub repo (main)  ── Vercel + DigitalOcean deploy from main
          ▲ push after merge ▲          ▲ push after merge ▲
          │ pull before task │          │ pull before task │
   Laptop A: you + Agent A              Laptop B: you + Agent B
   Lane A: scan & avatar                Lane B: recommend & render
```

## Setup (about 60–90 minutes, mostly in parallel)

1. **Tools:** Git, Python 3.11 or 3.12, Node 20+, Claude Code (`claude update`).
2. **Accounts.** Person A: Google AI Studio key; MongoDB Atlas free cluster (database user, network access `0.0.0.0/0` for the hackathon, copy the connection string). Person B: GitHub repo with your teammate as collaborator; Vercel (sign in with GitHub); DigitalOcean signup, and message the MLH coach for credits right away.
3. **Repo.** Person B unzips the setup into the repo, commits, and pushes; Person A clones.
4. **Contract.** Person A reads `contract/CONTRACT_NOTES.md` (10 minutes), runs `python3 -m contract.check_contract`, then commits `contract/FROZEN` and pushes.
5. **Backend (A).** `python3 -m venv .venv && source .venv/bin/activate`, then `pip install fastapi "uvicorn[standard]" pydantic python-multipart pymongo python-dotenv google-genai pillow`. Put `GEMINI_API_KEY` and `MONGODB_URI` in `backend/.env` (gitignored). Heavy CV libraries come later with their tasks.
6. **Frontend (B).** `npx create-next-app@latest frontend --ts --app --eslint --tailwind --no-src-dir --import-alias "@/*"`. Add rewrites in `next.config.ts` that proxy `/api/:path*` and `/media/:path*` to `process.env.BACKEND_URL ?? "http://localhost:8000"`.
7. **Deploy hello-world now.** DigitalOcean App Platform from the repo (at least 2 GB RAM, env vars set, HTTPS URL); Vercel with root directory `frontend` and `BACKEND_URL` set. Done when `https://<vercel-app>/api/health` returns the backend's JSON.
8. **Claude Code.** Open it in the repo root and accept the trust prompt. Check `/permissions` shows the deny rules from `.claude/settings.json`. Turn off connectors you won't use while coding with `/mcp`.

## The routine for every task

```bash
git checkout main && git pull --rebase           # 1. start from the latest main
git checkout -b a/A1-flatlay                      # 2. branch: <lane>/<task>-<name>
```

3. In Claude Code: `/task A1`. Answer its questions; let it work.
4. **Review before committing:** read the diff (`git diff`), run the task's check yourself, and run the app if the task touches something visible.
5. Let the agent commit, or commit yourself.
6. **Merge and push:**
   ```bash
   git checkout main && git pull --rebase
   git merge --no-ff a/A1-flatlay
   # run the check once more on main if anything came in from the other lane
   git push
   git branch -d a/A1-flatlay
   ```
7. Tell your teammate "pushed A1" (plus anything they need, e.g. a function signature). Every push to `main` redeploys both apps, so only merge working code.
8. `/clear` in Claude Code before the next task.

## Staying in sync

- **Cross-lane dependencies** are marked ⇄ in `TASKS.md`: A2 and A5 need B1; A6 needs S2; B1 needs S1. Do S1 and S2 first so nobody waits long.
- **Shared files:** `contract/` changes only with both of you agreeing (lane A edits, bumps `CONTRACT_VERSION`, pushes right away). `backend/app/main.py` is set up once in S1; after that each lane edits only its own `routes_a.py` / `routes_b.py`. `frontend/next.config.*` belongs to lane B.
- **If `main` breaks:** revert the last merge first (`git revert -m 1 <merge-commit>`, push), then debug on a branch.
- **Check-ins at each rung** (PRD Section 8): 5 minutes to demo the current state to each other, then re-scope if you're behind.

## When a second agent is OK

Only for a small, independent job that can't break anything, while your main agent is busy: tests for already-merged code, loading and error states for a finished screen, the README or Devpost draft. Run it on its own branch (`git worktree add ../closet-extra -b a/extra-tests`) and review it when your main task is done.

## Saving tokens

1. `/clear` after each task. A session left open all day re-sends its whole history with every message.
2. Sonnet by default; switch to Opus with `/model` only for a genuinely hard problem, then switch back.
3. After a long break, start with `/clear` instead of continuing.
4. Keep only the connectors you need (`/mcp`); check what's loaded with `/context`.
5. Look at screenshots yourself instead of asking the agent to.
6. Check `/usage` at each rung.

## Fixed times

- **Sun 7 AM:** feature freeze. Anything not solid is hidden from the UI.
- **By ~8:30 AM:** final video recorded on the deployed site.
- **By 10 AM:** Devpost submitted. 10–11 AM is buffer: table setup, reset the demo closet, charge laptops.
