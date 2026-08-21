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

## Static first, Playwright only when proven necessary

Try httpx and BeautifulSoup first. Move a site to Playwright only after the static fetch is shown to
return a shell without the postings — record that finding in the site recipe.

Playwright costs a browser process per run and is the main reason a workflow times out. It is a
per-site escalation, never the default path.

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
