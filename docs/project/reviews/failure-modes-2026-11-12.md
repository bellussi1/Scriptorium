# Failure mode inventory (prompt 4.1, 2026-11-12)

Based on `docs/ACTIVE_CONTEXT.md`, `docs/project/DESTRUCTIVE_TESTS.md`, the queue logs in
`data/queue-runs/` and the session history of 2026-11-11 and 2026-11-12. The table records
what has actually happened.

| Failure | Detected today by | Recovers today by | Time until a person acts | Needs someone watching? |
| --- | --- | --- | --- | --- |
| Translation killed (exit 137) when the app container restarted | the run exit code and the job row | resume from checkpoint (`Resuming ... from checkpoint index N`) after someone restarts the run | hours; two kills on Ashes at 22:51 and 22:59 on 11-11 | yes |
| Container restart with unknown cause (00:47 on 11-12) | container health, and a person noticing | the container comes back healthy; the run is restarted by hand | until someone notices | yes |
| Supervisor (agent) stopped | the heartbeat in `literary_queue.agent.json` stops moving | none: the agent is started by the user's BAT | until the user opens the Queue tab | yes |
| Auto supervisor dead or blocked | `literary_queue.auto.json` age (it was stale from 11-11 13:59) | the bounded restart (4.2) when it is running | not running now, so no recovery | yes |
| Status stale or wrong (`next` vs `running`) | nothing automatic; spotted by a person | the canonical `queue status --json`, read on demand | until someone asks | yes |
| Gate blocking (`needs_review`) | the status moves to `needs_review`; with `--stop-on-review` the run stops | a person reviews and approves, or corrects | until the review (hours to days) | yes, by design |
| Corrupted `jobs.db` or queue DB | integrity check (`health.json`: `queue_integrity`) | corrupt copy is preserved, a healthy snapshot is restored (destructive test 1) | minutes, if the snapshot is healthy | no, if the test path holds |
| App restart mid-run | the runner heartbeat | checkpoint resume (destructive test 3) | minutes | no |
| Pause now | `control.json` flags | the run stops at the next chunk; resume is manual | until someone resumes | yes |
| Resume duplicates an EPUB (`(1)` suffix) | a person sees a second file | none: the output path is not reused on resume (destructive test 2, finding 3) | until someone deletes the copy | yes |
| Upstream status left at `running` after a resumed CLI finishes | not detected | the queue flow still ends at `needs_review` | none needed for the queue | no |
| Model or provider error inside a chunk | the chunk fails and the job row shows it | retry of the failed book (`retry` route, intent) | until someone retries | yes |

## The three most expensive bottlenecks

1. **Human review of every book.** Each book stops at `needs_review`. The review itself
   is slow and it blocks the queue (the next book does not start by design).
2. **Silent staleness of status.** Several files (`auto.json`, `health.json`, plugin
   snapshot) can be old without any alarm. The cost is diagnosis time, as in prompt 2.1.
3. **Resume side effects.** A resumed run can create a duplicate EPUB and does not clear
   the upstream `running` state. Each case needs a person to clean up.

## Not covered by a test

- Supervisor crash during a gate hold (the auto supervisor's own state).
- Two writers at the same time (the agent and a CLI run) on the same queue database.
