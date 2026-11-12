# Two-minute review design (prompt 4.3, 2026-11-12)

Design only. Nothing here is implemented. It builds on endpoints that exist today:
`GET /api/literary/queue/books/<id>/quality`, `GET .../log`, `POST .../approve`,
`POST .../retry`, and the intent mechanism (`queue_intents.enqueue`, applied by the agent).

## Goal

A person approves or rejects a book in about two minutes, from the Queue tab, without a
terminal. The screen shows the gate, five passages side by side, the terms the glossary
does not cover, and the meaning errors already confirmed.

## Wireframe (text)

```
+-----------------------------------------------------------------------+
| Ashes of Man (#7)  · needs_review · job 25 · Sun Eater #5            |
| Gate: FAIL  forbidden 1 · pt-PT 4 · coverage 0.79 · length ok        |
| EPUBCheck 0 errors · validation ok · reader ok · series ok           |
+-----------------------------------------------------------------------+
| Passage 1 of 5                                          [ < ]  [ > ] |
|  SOURCE (EN)                       | TRANSLATION (pt-BR)              |
|  "She wore a saylash tattoo..."    | "Usava uma tatuagem saylash..."  |
|  flag: glossary term "saylash"     | flag: none                       |
+-----------------------------------------------------------------------+
| Terms outside the glossary (3):  Tavros · Calen Harendotes · Lin     |
| Confirmed meaning errors (0):   none                                 |
+-----------------------------------------------------------------------+
| Decision:  ( Approve )   ( Reject )                                  |
| Reason (required for reject): [______________________________]        |
| Recorded as: approve / reject · reviewer · time · audit snapshot     |
+-----------------------------------------------------------------------+
```

Five passages are drawn from the audit's samples (one per category when possible). The
gate line is read from the quality endpoint. Nothing on the screen calls the cloud.

## API contract

### Read

`GET /api/literary/queue/books/<id>/review`

```json
{
  "book": {"id": 7, "title": "Ashes of Man", "status": "needs_review", "job_id": 25},
  "gate": {"passed": false, "forbidden": 1, "pt_pt": 4, "coverage": 0.79,
           "epubcheck_errors": 0, "validation_blocking": 0,
           "reader_accepted": true, "series_applied": true},
  "passages": [
    {"id": "OEBPS/xhtml/026_chapter_022.xhtml:12", "file": "...",
     "source": "...", "target": "...", "flags": ["glossary: saylash"]}
  ],
  "terms_outside_glossary": ["Tavros", "Calen Harendotes", "Lin"],
  "meaning_errors_confirmed": [],
  "audit_snapshot": "data/audits/ashes-of-man-<ts>.json"
}
```

`passages` has at most five items, taken from the audit's `samples` (the source and the
target text are already stored there). `terms_outside_glossary` comes from the audit's
term section. `meaning_errors_confirmed` is empty until a meaning check has verdicts.

### Write

`POST /api/literary/queue/books/<id>/review`

```json
{"decision": "approve" | "reject", "reason": "required when reject", "job_id": 25}
```

- The route validates the body and returns `202` with a `token`, like the other write routes.
- The agent applies it as a new intent kind `review` (see the write map: the agent is the
  only writer). The route does not touch the database.
- `approve` runs the existing approve handler (job `completed`, `reviewed_at` set, Kindle
  export queued).
- `reject` sets the book to `failed` with the reason stored in `events`, so `retry` stays
  available. The book is not removed.
- The UI polls `GET /api/literary/queue/intents/<token>` until the intent is applied.

## Audit record

A new table `reviews`, written only by the agent when it applies the intent:

| column | content |
| --- | --- |
| `id`, `book_id`, `job_id` | identity |
| `decision` | `approve` or `reject` |
| `reason` | text, required for reject |
| `reviewer` | the local user name from the request |
| `duration_s` | time from opening the screen to the decision, sent by the UI |
| `audit_snapshot` | path of the audit JSON the review was based on |
| `created_at` | timestamp |

Every decision also writes an `events` row, so "Recent events" stays complete.

## Acceptance (for the later implementation)

- A reviewer can approve or reject a book from the Queue tab with the terminal closed.
- The screen fits one window; the five passages and the gate are visible without scrolling.
- Each decision leaves one `reviews` row and one `events` row, applied by the agent.
- Reject does not delete the book or its files.
- The UI never writes to the database directly.

## Not decided

- Whether `reject` should go to `failed` or to a new `rejected` state.
- Whether the reviewer name comes from a login or is typed.
- Whether the five passages are chosen by the audit or by the reviewer.
