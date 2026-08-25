# Crawling Rules

Applies to any code that fetches an external page, and to the scheduler and retry logic around it.

## One fetch client

All outbound requests go through `app/crawler/fetcher.py`. It owns the User-Agent, the per-host
delay, the timeout, the retry count and the robots.txt check. Nothing else calls `httpx`,
`requests` or a Playwright navigation directly.

A second call path is not a shortcut, it is a site getting hammered at an unthrottled rate under our
name. Once one module bypasses the client, no rate limit in the repository is true any more.

## Politeness is not optional

Before the first request to a host, read its `robots.txt` and honour a disallow on the target path.
A disallowed URL fails the crawler registration with a clear reason; it does not fetch anyway.

Keep a minimum delay between requests to the same host, configured by `CRAWL_DELAY_SECONDS`. The
default is deliberately slow. A workflow that finishes late is fine; a workflow that gets our IP
banned takes the site away permanently.

Identify honestly in the User-Agent — a name and a contact. Never impersonate a browser to defeat a
block, and never work around a login wall, a CAPTCHA or a rate limit that a site put up on purpose.
The PRD lists those sites as out of scope. When one turns up, report it and stop.

## The browser opens while registering, not while running

A crawler stores two paths, `crawlers.list_mode` and `crawlers.detail_mode`, each `static`, `api`
or `playwright`. Mixing them is a normal choice, not a workaround.

Registration finds the path itself (`app/selector/discovery.py`). It fetches the list statically
first and only opens a browser when that cannot reach a detail page — then it clicks one item,
watches what the page requests, and calls that request again through the shared client before
adopting it. What gets stored is the request, so the run that follows needs no browser.

As measured on 2026-08-25 all six target sites serve both list and detail over httpx, four of them
through a JSON or HTML-fragment API. **No site needs a browser per run.** A browser process costs
150~300MB and several seconds per page and is the main reason a workflow times out, so `playwright`
stays a per-site decision backed by a measurement, never a default.

Prove it before moving a site either way. The test-run screen runs one crawler under a different
mode for one run without changing what is stored, and the field match counts are what decides.
Record the finding in the site recipe.

The judgement is a proposal. The operator changes the stored path on the crawler screen and nothing
overwrites that choice afterwards.

## Failure is data

A run that extracts nothing is a failure, not an empty success. A selector matching zero elements
means the site changed, and that must reach `crawl_runs.fail_count` and the workflow's failure
badge. Never swallow it into a clean run with zero new postings.

Distinguish these three in the error message, because they need different fixes:
transport failure (timeout, 5xx, connection reset), selector miss (fetched fine, matched nothing),
parse failure (matched, but the field could not be read).

Retry transport failures up to three times with backoff. Never retry a selector miss — the page will
not change in four seconds, and the retry only doubles the load on a site that already answered.

## Scheduling

APScheduler runs in the API process. Jobs are registered from the `workflows` table at startup and
updated when a workflow's interval or status changes — the table is the source of truth, not the
scheduler's memory.

Every workflow run is bounded by a timeout and writes a `crawl_runs` row whether it succeeded,
failed, or was killed. A run with no row is a run nobody can debug.

Concurrent runs are capped by a single semaphore. One workflow never has two runs in flight at once;
a run still going when its next tick arrives is skipped, and the skip is logged.

## Change detection

A posting is identified by a content hash over its stable fields, not by row order or list position.
Re-crawling an unchanged page inserts nothing. The hash and what goes into it are stated in
`.claude/docs/data-model.md`.
