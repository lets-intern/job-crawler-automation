# Git Rules

## Never commit or push to main

**Check the current branch immediately before every commit.**

```bash
git branch --show-current
```

If it says `main`, stop. If you already committed, create a branch, move the commit, and reset main.

Creating a branch when the work starts is not enough. What matters is which branch the terminal is
on at commit time, and that is only knowable then. `git status` shows it too, buried under the file
list — run `--show-current` on its own.

With several sessions or agents in one repository, one switching branches moves the others.
If another session is running, check again immediately before committing.

## Push only when asked

Commit when the work reaches a meaningful unit. Push only when the user explicitly asks.
Before pushing, the type check and the relevant tests must pass.

## Never commit secrets or collected data

`.env`, the SQLite file, `debug_snapshots/` and anything under `.playwright/` stay out of the
repository. Check `git status` before staging. An API key in history is a key that must be rotated.

## Commit messages

Conventional Commits, subject in Korean, 72 characters or less.

```
type(scope): what changed

type:  feat | fix | refactor | style | docs | test | chore
scope: crawler | selector | workflow | scheduler | normalize | api | ui | db | infra

Co-Authored-By: Claude <noreply@anthropic.com>
```

Do not write a model name or a context-window size into the trailer. It goes stale and says nothing
about the change.
