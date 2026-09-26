# STATUS.md — live coordination between Lane A and Lane B

A status board, not a log. Both agents read this before starting a task and
write to it when starting and finishing one, so scope conflicts show up
immediately instead of surfacing as a merge conflict or a broken build later.

## In progress

| Lane | Task | Files (scope) | Started |
| --- | --- | --- | --- |
<!-- Add a row here right after you start a task. Remove it (move to
     Recently finished below) as soon as you're done — a stale row here
     reads as "still being edited" to the other lane. -->

## Recently finished

| Lane | Task | Files touched | Check result | Notes for the other lane |
| --- | --- | --- | --- | --- |
<!-- Move your row here from "In progress" when you finish. Keep the
     "Notes" column for things the other lane actually needs: a function
     signature they'll call, a schema field you added, a fixture you
     changed. Leave it blank if there's nothing to flag. -->

## Rules

- **Before starting:** check the **In progress** table. If any row's files
  overlap with the files your task lists, stop and tell your human before
  touching anything — don't assume it's safe just because your lane "owns"
  that folder on paper.
- **A row older than a couple of hours with no matching commit on `main`**
  is probably stale (laptop closed, session cleared). Don't treat it as a
  hard lock — flag it to your human instead of either barging in or
  blocking indefinitely.
- This board is for scope/overlap visibility, not a replacement for
  `git pull` — always pull before starting a task regardless of what this
  file says.
