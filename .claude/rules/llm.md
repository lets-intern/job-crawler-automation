# LLM Rules

Applies to every model call: selector generation, posting classification, and anything else.

## The model is a proposer, never an authority

A generated selector is a hypothesis. It becomes real only after the test run in
`.claude/skills/crawl-test/SKILL.md` extracts plausible data from the live page and a human accepts
it. Nothing reaches `workflows` on the model's word alone.

The operator can edit any generated selector by hand. Hand edits are the fix of first resort when
generation is close but wrong. Never regenerate over an edited selector without being asked.

## Prompt input is bounded and cleaned

Never send a raw page. Strip `script`, `style`, `svg`, comments and inline event handlers, then
sample the repeating region rather than sending every list item — three or four siblings carry the
same structural signal as sixty and cost a fraction.

Cap what is sent. If the cleaned HTML still exceeds the cap, narrow the region before truncating
blindly, and say in the response that the input was narrowed.

## Output is validated, not trusted

Constrain the response to the selector JSON schema and validate it before it touches the database.
A response that does not parse, or that names a field the schema does not have, is a failure — log
it and surface it to the operator. Do not repair it silently by guessing what was meant.

Every generated selector must be run against the fetched HTML at generation time. A selector that
matches zero nodes never gets presented as a success; it is presented as a failed field, with the
name of the field that failed.

Retry generation at most once, and only for a malformed response. Repeated failures are an operator
decision — hand-write the selector or drop the site.

## Providers

Four providers are supported: Gemini, Claude, GPT and Qwen. The operator picks which one a given
call uses. This replaces the earlier single-provider rule (2026-08-24, `.claude/tasks/todo/prd-crawler-v2.md`).

One thin call site, not an abstraction tower. A provider entry states its SDK, its model setting and
how it returns token counts; nothing else in the codebase branches on which provider is in use. If a
provider needs its own prompt shape, that belongs in the provider entry, not scattered through the
callers.

Every provider is optional. A missing key disables that provider and says so; it never falls back to
a different one silently — a call that quietly went to another model makes the cost log a lie.

Check the current documentation of the provider you are calling before writing or changing a call.
Model IDs, pricing and parameter shapes change; do not write them from memory. Model IDs live in
settings, not in a source file.

API keys come from the environment and never from a source file, a template, a log line or a
committed `.env`. `.env.example` documents the names only.

## Every call is logged

Log the provider, model ID, what the call was for, input and output token counts, latency and
whether it succeeded. Write it to the log database, not the operating one — a log table inside the
data the operator exports and imports makes both slower for no benefit.

v1 had one expensive call, at selector generation. v2 adds a classification call per posting, so the
count scales with how much is collected. Without these numbers no cost question can be answered.
