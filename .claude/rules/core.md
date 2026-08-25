# Core Rules

These apply to every task in this repository. The other files in `.claude/rules/` add to them and
never repeat them. When a rule appears in two places, the one here is not the copy — delete the copy.

## Language

**Always respond to the user in Korean.** The user is a Korean developer.

Write in English the files that load on every session: `CLAUDE.md`, `.claude/rules/**`,
`.claude/agents/**`, and every directory tree and path mapping table wherever it appears. English
costs fewer tokens for the same instruction, and these are read by the model, not by a person.

Skills are the exception. A `SKILL.md` `description` holds the Korean phrases the user actually says
("셀렉터 뽑아줘", "워크플로우 상태 봐줘"), and those phrases are what make the skill trigger. Do not
translate them. A skill body stays in whatever language it is already in.

Write documents for humans in Korean: everything under `.claude/docs/`, `.claude/tasks/`,
`.claude/site-recipes/`, `.claude/troubleshooting/`, `.claude/dev-records/`, `**/references/`,
PRDs, reports and commit messages.

## What this service is

A crawling automation backend, not a job board. Its output is normalized job posting data that a
separate job board service consumes over the REST API in `.claude/docs/api-contract.md`.

Two consequences that decide arguments before they start.

There is no end-user UI. The web screens exist for one operator to register selectors, inspect runs
and fix rules. Do not design for anonymous traffic, sessions, or public-facing polish.

The pipeline is the product. When a choice is between a nicer screen and a run that fails loudly
with a usable reason, the run wins.

## Think before coding

State assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them rather than silently picking one.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop, name what is confusing, and ask.

## Simplicity first

Write the minimum code that solves the problem. Nothing speculative.

The PRD names its own non-goals: no multi-user auth, no distributed crawling, no login or CAPTCHA
bypass. Those are decisions, not gaps. Do not implement toward them.

The stack is deliberately small — one FastAPI process, APScheduler in-process, SQLite in one file,
HTMX over Jinja2 templates. Do not introduce Celery, Redis, Postgres, a SPA framework, a build step,
or a second container. If a real limit is hit, report the measurement and let the user decide.

No abstractions for single-use code. No plugin layer for one crawler. No error handling for
impossible scenarios.

## Surgical changes

Touch only what you must. Clean up only your own mess.

Do not improve adjacent code, comments or formatting. Do not refactor what is not broken.
Match the existing style even where you would do it differently.
If you notice unrelated dead code, mention it. Do not delete it.

Remove imports and helpers that your own change made unused. Nothing else.

The test: every changed line traces directly to the user's request.

## Goal-driven execution

Turn the task into a verifiable goal before starting.

Selector generation works becomes run it against a saved HTML fixture and assert the extracted
fields. Fix the dedup bug becomes write a test that ingests the same posting twice and asserts one
row. Add a normalization rule becomes assert the raw value in and the normalized value out.

Network is not a test dependency. Every parser and normalizer test runs against a fixture under
`tests/fixtures/`. Only an explicitly marked live test hits a real site.

## Project invariants

Raw HTML is never persisted as product data. Parsed results go to `raw_jobs`; only the most recent
failures may keep an HTML snapshot, in the debug area, with a retention bound. `.claude/rules/data-safety.md`
states the shape.

`raw_jobs` is append-only and never rewritten by a normalization change. Re-normalization writes
`normalized_jobs`, never the source it derived from.

Every outbound HTTP request goes through the one shared fetch client. No module calls `requests.get`
or `httpx.get` directly — that is how rate limits, the User-Agent and retries get bypassed.
`.claude/rules/crawling.md` states why.

## The other rule files

| File | Applies when |
|---|---|
| `.claude/rules/writing.md` | Writing any document, report or HTML deliverable |
| `.claude/rules/crawling.md` | Fetching any external page, or changing the fetch client, scheduler or retry logic |
| `.claude/rules/llm.md` | Calling any model provider, building a prompt, or parsing a model response |
| `.claude/rules/data-safety.md` | Touching the schema, a migration, the SQLite file, or delivery state |
| `.claude/rules/git-safety.md` | Committing, pushing, or writing a commit message |

An agent declares which of these apply to it and does not restate their contents.
