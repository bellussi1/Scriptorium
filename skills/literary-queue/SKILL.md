---
name: Literary Queue
description: Operate the TraducaoLLM fork's literary translation queue, resources, EPUB gates and model benchmarks. Use when starting, pausing or reviewing a book, changing a book's provider/model, validating an EPUB, or running a model comparison for English-to-Brazilian-Portuguese literary translation.
---

# Literary Queue

This is the project-specific layer for the TranslateBooksWithLLMs fork. The
upstream `translate-books-with-llms` skill explains the raw engine; this skill
explains the queue, the editorial resources, the review gate and the model
policy around it.

## Non-negotiables

1. **One book at a time, one chunk at a time.** The queue accepts `mode=next`
   only. Always run with `--max-books 1 --stop-on-review --parallel 1`.
2. **Never publish.** Translated works are for the owner's personal reading and
   never leave this machine.
3. **Never rewrite literary text to fix metadata.** Metadata work is metadata
   work; prose edits are a separate editorial decision.
4. **Secrets come from `.env` or the environment.** Never hardcode, log or
   commit a key, token or URL containing one.
5. **No cloud spending without an explicit cap.** Local Ollama is the default.
   Check the balance and agree on a cap before any cloud run. The queue has a
   provider gate (`QUEUE_ALLOW_CLOUD=true`) but no hard dollar cap by itself.
6. **The review gate is mandatory.** Cloud drafts skip the Ollama-only
   refinement pass; the human review is the quality gate.

## Current model policy (2026-11-10)

| Series | Primary | Fallback | Not preferred |
|---|---|---|---|
| The Sun Eater | Gemini 3.8 Flash (`provider=gemini`, `model=gemini-3.8-flash`) | Claude Haiku 5.5 (`litellm`, `anthropic/claude-haiku-5-5`) | DeepSeek, Q4 |
| Realm of the Elderlings | Index-Translate 9B (`ollama`, `hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M`) | Q4 for small jobs | Cloud unless the book is explicitly benchmarked |
| Other series | Index 9B local | Q4 local | Cloud without a benchmark |

Evidence: `docs/project/reviews/sun-eater-model-selection-2026-11-10.md`.
Gemini leads chrF and the blind A/B on Sun Eater; Index is the free local
fallback and has perfect long-chapter term compliance. Q4 omits content on the
long chapter. DeepSeek is more expensive per word with lower probe compliance.

## Budgets

These are snapshots; confirm the current balances before spending.

- Gemini: R$ 30 credit + R$ 61 monthly GCP (R$ 91 total on 2026-11-10).
- Claude: US$ 2.47.
- DeepSeek: US$ 1.38.

Measured Gemini rate: about **US$ 14.76 per million source words**. Haiku about
**US$ 3.54–5.73/M**. A 300k-word Sun Eater book is about US$ 4.4 on Gemini and
US$ 1.05–1.70 on Haiku. Never start a cloud book without a cap and a review
gate.

## Before starting a book

```bash
python -m src.literary.cli queue next
python -m src.literary.cli queue list --status pending
python -m src.literary.cli queue plan --book-id <id>
python -m src.literary.cli resources validate --root literary-resources
```

Check:

- `docs/ACTIVE_CONTEXT.md` for runtime, queue and budget state.
- the book's `status` is `pending` (change it with `queue set-state` if paused);
- the provider/model matches the policy above;
- the source EPUB exists and the compiled glossary/style look right;
- no other translation is active and the queue agent is online;
- for cloud, the balance and an explicit cap.

## Running one book

The host agent is required. Start it once:

```powershell
start-queue-agent.bat
```

It watches `data/literary_queue.run-request.json`. The UI "Run next" writes that
request. The agent always runs exactly one book and stops at the review gate:

```bash
python -m src.literary.cli queue run-all \
  --db data/literary_queue.db --parallel 1 --refine-limit 0 \
  --max-books 1 --stop-on-review \
  --export-kindle --outputs translated_files --kindle-out translated_files/kindle
```

Useful commands:

```bash
python -m src.literary.cli queue set-model --book-id <id> --provider <p> --model <m>
python -m src.literary.cli queue set-state --book-id <id> --state pending|paused
python -m src.literary.cli queue pause-now
python -m src.literary.cli queue approve --book-id <id> --job-id <id>
python -m src.literary.cli queue export-kindle
```

`queue approve` records `reviewed_at`; without it, Kindle export skips the book
as "not reviewed".

## EPUB gates

A book is not done when the translation process exits. It is done when:

1. the output EPUB exists and the reader repair ran (Sun Eater);
2. **EPUBCheck is 0 fatals / 0 errors / 0 warnings**;
3. `validate epub` reports `blocking: 0`; warnings are explained;
4. the TOC is not the book title repeated; chapter labels are correct;
5. the OPF package version matches its metadata (`dc:`/`opf:meta` for EPUB2,
   `property`/`refines` only for EPUB3), `unique-identifier` matches the
   identifier id, and the NCX `dtb:uid` matches the OPF identifier;
6. the review gate has been passed and the book is exported to Kindle.

```bash
python -m src.literary.cli validate epub \
  --source "<source.epub>" --target "<translated.epub>" --language pt-BR
```

The Fool's Errand case is the reference failure: EPUB3 meta elements inside an
EPUB2 package, duplicate cover meta, `unique-identifier="uuid_id"` with no such
id, and every TOC label replaced by the book title. Repair metadata, never the
prose.

## Resources

```
literary-resources/
  global/
  <author>/
    <universe>/
      <subseries>/
        <book>/
```

- `first_appearance` filters terms by book order; a term that appears in book 1
  must have `first_appearance: empire-of-silence` (or the correct slug), not a
  later book.
- `aliases` and `alias_targets` keep short forms distinct (`Hadrian` must not
  become `Hadrian Marlowe`).
- `forbidden` renderings are hard constraints.
- `confidence` is `confirmed`, `reviewed` or `provisional`; only confirmed
  terms should be treated as official.
- After resource edits, run `resources validate` and the resource/corpus tests.

## Recurring errors to check in review

- **pt-PT forms:** `tu/despertaste`, `quilómetros`, `fazer-vos`, `se tinha
  deslocado`, `contacto`, `de facto`, `demónio`, `a dançar`. The target is
  pt-BR.
- **Gender agreement:** `o inquisidor` for a female inquisitor; `a capitã` vs
  `o capitão`; pronoun agreement around `Switch` and Cielcin characters.
- **Names and terms:** `Pale → Pálido`, `Quiet → Quieto`, `Forum → Fórum`,
  `Gibson of Syracuse → Gibson de Siracusa`, `Siran` (short form),
  `Simeon, o Vermelho` (not `Ruivo`).
- **English leakage / title calques:** `Devil's Rest`, `Simeon the Red`,
  `Meidua Devils`, `Chantries`, `Obdurate`/`Obdurante`.
- **TOC and OPF:** repeated labels, EPUB2/EPUB3 metadata mix, identifier
  mismatch, duplicate cover.
- **Long-chapter omission:** Q4 lost the opening scene; always compare output
  length and the first/last paragraphs against the source.
- **Checkpoint mixing:** changing provider/model after a partial run requires
  clearing the resume state, or the book will mix models.

## Benchmarks

The Sun Eater corpus, probes and long chapter are built with:

```bash
python scripts/build_sun_eater_corpus.py
python scripts/audit_sun_eater_resources.py
```

Local dev/test/long chapter:

```bash
python scripts/benchmark_fase_d.py --corpus <corpus.jsonl> \
  --models hy-mt2-7b index-translate-9b --repeats 1 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root <out>
```

Cloud dev/test/probes:

```bash
docker compose -f docker-compose.dev.yml exec -T -e TEMPERATURE=0 app \
  python scripts/benchmark_cloud.py --corpus <corpus.jsonl> \
  --models gemini-3.8-flash claude-haiku-5-5 --concurrency 2 \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book "Empire of Silence" \
  --resource-book-order 1 --out-root <out>
```

Scoring and A/B:

```bash
python scripts/score_probes.py --probes <probes.jsonl> --run-dir <run> --model <model>
python scripts/compare_cloud_runs.py --cloud-run <cloud> --local-run <local>
python scripts/make_pairwise_sheet.py --corpus <dev.jsonl> --run-dir <combined> \
  --model-a index-translate-9b --model-b gemini-3.8-flash --out <sheet>
python scripts/make_judge_batches.py --sheet <sheet> --out-dir <batches> \
  --batch-size 14 --series "The Sun Eater"
python scripts/run_claude_judge.py --batches <batches> --out <judgments> \
  --raw-dir <raw> --model sonnet
python scripts/analyze_pairwise.py --input <judgments> --sheet <sheet> \
  --key <key> --reference-model index-translate-9b
```

Long chapter:

```bash
docker compose -f docker-compose.dev.yml exec -T app \
  python scripts/run_long_context.py --corpus <long.jsonl> \
  --cloud-model gemini-3.8-flash \
  --resource-author christopher-ruocchio --resource-universe sun-eater \
  --resource-subseries= --resource-book-order 1
```

Rules for a valid comparison:

- temperature 0; one repeat is enough after confirming determinism;
- the same 73-form glossary/style prompt for every model;
- probes score terms, names and swaps, not only chrF;
- blind A/B with a non-contestant judge (Claude Sonnet is acceptable; do not
  use a contestant as the only judge);
- include the long chapter and compare output length, not only chrF;
- record cost per million source words.

## ACTIVE_CONTEXT checklist

At the start of a session, read `docs/ACTIVE_CONTEXT.md`.

Before stopping, update it with:

- branch and last commit;
- runtime: agent online/offline, runner active/idle, app ports;
- translation state: current book, status, provider/model, checkpoint state;
- cloud budgets and spend since the last update;
- benchmark position and the next decision;
- any partial work that must not be resumed blindly.

Do not duplicate the full report; link to
`docs/project/reviews/` and `docs/project/README.md`.

## What not to do

- Do not run `queue run-all` without `--max-books 1 --stop-on-review`.
- Do not use `--parallel` greater than 1.
- Do not start a cloud book without a cap and a balance check.
- Do not use Opus; the agreed cheap models are Gemini Flash, Haiku and DeepSeek.
- Do not translate from a cloud provider and claim local privacy.
- Do not edit prose to fix a TOC, an OPF field or a tag.
- Do not commit `.env`, keys, `Custom_Instructions/sun-eater-2.yaml` or
  `.taste-skill/`.
