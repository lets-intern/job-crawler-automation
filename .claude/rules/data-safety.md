# Data Rules

Applies to the schema, migrations, the SQLite file and delivery state.

## Raw and normalized are separate, and one direction only

`raw_jobs` holds what the crawl extracted, unmodified, append-only. `normalized_jobs` holds what the
rules produced from it. Normalization reads raw and writes normalized. It never edits raw.

That is what makes a bad normalization rule recoverable: the source is still there, so a re-run
fixes it. A pipeline that normalizes in place has one bad regex between it and permanent data loss.

## Raw HTML is not stored

Store the parsed result, not the page. The exception is a debug snapshot for recent failures, kept
under a bounded retention and never read by the pipeline itself. It exists to answer "what did the
page look like when the selector broke" and nothing else.

## Delivery state belongs to the consumer boundary

`normalized_jobs.delivered_at` records that the job board fetched a row. Only the delivery API path
writes it. A crawl, a re-normalization or a manual fix must not clear or backdate it — that would
resend rows the consumer already has.

The API contract that reads it is `.claude/docs/api-contract.md`. A change to either side changes
both files in the same commit.

## Migrations

The schema changes through a migration file, never by editing a live table by hand and never by
deleting the database file to get a fresh schema. The SQLite file is a Docker volume holding real
collected data, and the collection cannot be replayed.

Back up the file before running a destructive migration. State in the task record what the migration
does and how to reverse it.

## Local data is real data

Do not run `DELETE`, `DROP` or `UPDATE` without a `WHERE` against the operating database, and do not
run one at all unless the user asked for it. Read queries need no permission; writes outside the
application code need to be requested explicitly.
