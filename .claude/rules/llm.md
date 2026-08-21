# LLM Rules

Applies to selector generation and any other Gemini API call.

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

## API usage

The provider is the Gemini API through the `google-genai` Python SDK. Do not add an adapter layer
for a second provider.

Check the current Gemini documentation before writing or changing an API call. Model IDs, pricing
and parameter shapes change; do not write them from memory. The model ID lives in `GEMINI_MODEL`,
not in a source file.

The API key comes from the environment and never from a source file, a template, a log line or a
committed `.env`. `.env.example` documents the name only.

Log the model ID, token counts and latency per generation. Selector generation is the one expensive
call in this service, and without those numbers no cost question can be answered later.
