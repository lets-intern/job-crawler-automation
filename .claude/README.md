# `.claude/`

The directory tree, the agent list, the skill list and the situation-to-path table live in the root
`CLAUDE.md`. They are not repeated here.

This file covers only what `CLAUDE.md` does not: how the kinds of file differ, and what belongs where.

## The kinds of file

Each kind does one job. When two files could hold the same instruction, this table decides which one
does, and the other references it by path.

| Kind | Holds | Does not hold |
|---|---|---|
| `hooks/` | What must run whether or not the model chooses to. Enforcement | Guidance. A hook that only advises should be a rule |
| `rules/` | Constraints. One rule, one owner, stated once | Procedure. How to do something is a skill |
| `skills/` | The general, minimum procedure for one task | A specific site's quirks — those go in `site-recipes/` |
| `agents/` | A role composed from skills, the rules it obeys, and what it must never do | The contents of those skills and rules. It names their paths |
| `docs/` | How the system works, for a person | Constraints. Those are rules |
| `site-recipes/` | What was learned about one site, with the evidence | Selector text. The database is the source of truth for that |

Two consequences worth stating outright.

A skill never calls another skill. Sequencing is an agent's or a command's job. A `SKILL.md` that
tells the reader to run a second skill has moved orchestration into the wrong layer.

A skill body must survive a refactor of the product code. If a change to `app/crawler/` forces an
edit to a `SKILL.md`, the volatile part belonged in `docs/` or a site recipe.

## Where a written artefact goes

| Output | Directory |
|---|---|
| PRD, task file | `tasks/todo/`, then `tasks/done/` |
| A finding about one site | `site-recipes/<domain>.md` |
| An issue with no explanation yet | `troubleshooting/` |
| Handover notes for a person | `dev-records/` |
| How a subsystem works | `docs/` |
| A constraint that must hold next session | `rules/` |

## Adding a rule

A rule file states the constraint and why it exists, in English, and stays short enough to be read
every session. Evidence behind it — an incident, a measurement, a site inventory — goes in
`rules/references/` in Korean and is read only when someone doubts the rule.

That split is what keeps a rule stable while the code it describes moves.

A new rule must be listed in the table at the bottom of `rules/core.md` and in the tree in
`CLAUDE.md`. A rule nobody is pointed to is a rule nobody follows.
