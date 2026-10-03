# ADR 0804: Verify asynchronous removal of the owned PostgreSQL drill container

Date: 2026-10-03

Status: Accepted

## Context and decision

GitHub server-boundaries job111122861548 at517e6a8f completed the migration,
history-refusal and restore assertions but failed its immediate post-stop
cleanup probe. Docker may finish automatic removal after `stop` returns.

Require a complete64-character container ID and verify that the expected name
still resolves to that ID before stopping the exact ID. After stop, allow five
seconds with100ms polling. Only a successful `docker ps --all --no-trunc --quiet`
query filtered by the full ID and returning no container proves removal.
Daemon failure, timeout, unexpected identity or persistent container fails the
drill. Do not treat an arbitrary unsuccessful inspect as proof of absence.

## Evidence and rollback

Ten regressions cover immediate/delayed removal, persistent containers, daemon
and timeout errors, unexpected returned identity and invalid/mismatched IDs
without stopping. The full drill/matrix selection passes29tests with no skips.
Actual PostgreSQL17.10 drill and16.14/17.10 matrix through0093 pass with cleanup
confirmed in34.83s and92.16s. New source-bound reports use the CLEANUP suffix;
all four previous retained reports remain byte-identical. The separate0094
branch must regenerate its own reports against its actual runner and migrations.

No product database, dependency policy or other cleanup runner is changed.
Rollback reverts the runner and latest-evidence references; it restores the
immediate-probe race and ambiguous inspect behavior. Remote CI must verify the
new commit independently of the successful local drills.
