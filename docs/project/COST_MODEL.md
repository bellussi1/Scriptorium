# Cost model

Prices checked on **2026-11-07**; token ratios measured on the user's EPUBs on
the same date. All values are USD. The model is implemented in
`src/literary/cost.py` and can be run without a cloud key.

## 1. Why a word-to-token conversion would be wrong

The English word count falls by about 3% in the Portuguese samples (official
editions for Farseer/Sun Eater; the user's unreviewed draft for Lonesome Dove),
but the **token count rises**. Portuguese accents, contractions and word forms
tokenize worse under `cl100k_base`. Using a word ratio would underestimate the
output cost.

Measured on the first three long chapters of each available edition:

| Edition | Words | cl100k tokens | Tokens/word |
|---|---:|---:|---:|
| Lonesome Dove EN | 14,424 | 17,683 | 1.226 |
| Lonesome Dove PT | 13,946 | 23,456 | 1.682 |
| Assassin's Apprentice EN | 23,499 | 31,116 | 1.324 |
| Assassin's Apprentice PT | 24,410 | 42,350 | 1.735 |
| Royal Assassin EN | 18,182 | 23,100 | 1.271 |
| Royal Assassin PT | 18,678 | 32,979 | 1.766 |
| Howling Dark EN | 13,828 | 18,650 | 1.349 |
| Demon in White EN | 11,267 | 14,713 | 1.306 |
| Império do Silêncio PT | 10,453 | 18,646 | 1.784 |

**Adopted defaults:** 1.30 English tokens/word; 1.36 Portuguese output tokens
per English input token. The paired ratios are 1.31–1.39; 1.36 is the midpoint.
The actual provider tokenizer may differ; see §7.

## 2. Formula

For a single pass:

```
source_tokens   = words × 1.30
chunks          = ceil(source_tokens / (450 × 0.78))
input/chunk     = 450 × 0.78 + system_prompt + user_template
                  + glossary + style + context
output/chunk    = 450 × 0.78 × 1.36
input_tokens    = chunks × input/chunk × (1 + retry_rate)
output_tokens   = chunks × output/chunk × (1 + retry_rate)
```

Defaults: system prompt 500 tokens, user template 60, context 50, retry 10%,
cache hit on 75% of the stable prefix, 450-token chunks at 78% fill. A
source-aware refine pass is priced at 1.85× the input and 0.97× the output of a
translation chunk. A selective review can be priced on a fraction of the book.

These are deliberately explicit assumptions, not hidden “magic numbers”. Change
them with the CLI options in §6 and re-run.

## 3. Cost per word count (single pass, standard context)

| Words | DeepSeek Flash peak | DeepSeek off-peak | Gemini 3.8 Flash | Gemini batch | GPT-6 Luna | Claude Haiku 5.5 | Local |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100k | $0.31 | $0.15 | $0.92 | $0.46 | $0.12 | $0.12 | $0 |
| 250k | $0.76 | $0.38 | $2.30 | $1.15 | $0.31 | $0.31 | $0 |
| 500k | $1.53 | $0.76 | $4.60 | $2.30 | $0.61 | $0.61 | $0 |
| 1M | $3.06 | $1.53 | $9.20 | $4.60 | $1.23 | $1.23 | $0 |

With a conservative “no cache, 25% retry” assumption, DeepSeek Flash peak is
about $0.40 / $1.00 / $1.99 / $3.99 for the same sizes.

## 4. Refinement and hybrid scenarios

| Scenario | 100k | 250k | 500k | 1M | What it means |
|---|---:|---:|---:|---:|---|
| A. DeepSeek Flash, one pass (peak/off-peak) | $0.31 / $0.15 | $0.76 / $0.38 | $1.53 / $0.76 | $3.06 / $1.53 | Cheapest usable draft |
| B. DeepSeek Flash + source-aware refine | $0.71 / $0.35 | $1.76 / $0.88 | $3.52 / $1.76 | $7.05 / $3.52 | Cheap draft + review |
| C. Gemini 3.8 Flash, one pass (standard/batch) | $0.92 / $0.46 | $2.30 / $1.15 | $4.60 / $2.30 | $9.20 / $4.60 | Strong single pass |
| C+. Gemini 3.8 Flash + refine (standard/batch) | $2.07 / $1.04 | $5.17 / $2.58 | $10.34 / $5.17 | $20.68 / $10.34 | Strong + review |
| D. Local Hy-MT2 + 10% Gemini review (2 passes) | $0.21 | $0.52 | $1.04 | $2.07 | Hybrid |
| E. All local | $0 | $0 | $0 | $0 | No API cost |

**Reading:** the API bill is small. The dominant cost of a serious literary
translation is editorial time, not tokens. A $2,000 human review of a 300k-word
novel is not made cheaper by saving $20 on the API.

## 5. Real books and sagas

### One book

| Book | Words | DeepSeek peak | DeepSeek off-peak | DeepSeek + refine | Gemini 3.8 | Gemini batch | Gemini + refine | GPT-6 Luna |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lonesome Dove | 365,575 | $1.12 | $0.56 | $2.58 | $3.36 | $1.68 | $7.56 | $0.45 |
| Farseer 1 | 165,049 | $0.51 | $0.25 | $1.16 | $1.52 | $0.76 | $3.42 | $0.20 |
| Sun Eater 2 | 264,961 | $0.81 | $0.41 | $1.87 | $2.44 | $1.22 | $5.48 | $0.33 |

### Sagas / queue

| Queue | Words | A DeepSeek peak | A off-peak | B DeepSeek refine peak | C Gemini | C batch | C+ Gemini refine | D hybrid | E local |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Hobb: Liveship + Tawny Man + Rain Wild + Fitz/Fool | 3,360,705 | $10.28 | $5.14 | $23.68 | $30.91 | $15.46 | $69.48 | $6.95 | $0 |
| Sun Eater 2–7 | 1,645,495 | $5.03 | $2.52 | $11.60 | $15.14 | $7.57 | $34.02 | $3.40 | $0 |
| Sun Eater novellas (optional) | 189,771 | $0.58 | $0.29 | $1.34 | $1.75 | $0.87 | $3.92 | $0.40 | $0 |
| Hobb + Sun Eater main | 5,006,200 | $15.32 | $7.66 | $35.28 | $46.05 | $23.02 | $103.50 | $10.35 | $0 |
| All target books incl. Lonesome (hypothetical retranslation) | 5,561,546 | $17.01 | $8.51 | $39.19 | $51.16 | $25.58 | $114.98 | $11.50 | $0 |

The last row is a sensitivity case only: Lonesome Dove has the user's unreviewed
PT draft, not an official edition, and Farseer 1–3 already have official PT
editions. They are not in the production translation queue; they are
reference/benchmark material. Rain Wild is included in the Hobb total as a
sensitivity but is deferred by the user and is not in the active queue.

### Context-rich conservative variant

If each chunk carries 1,500 tokens of chapter context, 400 tokens of glossary,
300 tokens of style and a 20% retry rate:

| Words | DeepSeek peak | DeepSeek off-peak | DeepSeek + refine | Gemini 3.8 | Gemini batch | Gemini + refine | GPT-6.1 Terra |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100k | $0.59 | $0.30 | $1.53 | $1.66 | $0.83 | $4.17 | $2.19 |
| 250k | $1.48 | $0.74 | $3.82 | $4.13 | $2.07 | $10.41 | $5.48 |
| 500k | $2.96 | $1.48 | $7.64 | $8.26 | $4.13 | $20.82 | $10.95 |
| 1M | $5.91 | $2.96 | $15.27 | $16.53 | $8.26 | $41.63 | $21.90 |

For the 5.0M-word Hobb + Sun Eater main queue: DeepSeek context-rich peak
**$29.59**, off-peak **$14.79**, Gemini context-rich **$82.73**, Gemini batch
**$41.37**, GPT-6.1 Terra context-rich **$109.65**. For all target books:
DeepSeek **$32.87 / $16.43**, Gemini **$91.91**, batch **$45.96**, Terra
**$121.81**.

## 6. How to run the estimator

```bash
# One model, one word count
python -m src.literary.cli estimate --words 300000 \
  --provider gemini --model gemini-3.8-flash

# All A-E scenarios
python -m src.literary.cli estimate --words 300000 --all-scenarios

# A book from the inventory
python -m src.literary.cli estimate --inventory data/calibre/targets.json \
  --calibre-id 311 --scenarios A B C D E

# A whole series
python -m src.literary.cli estimate --inventory data/calibre/targets.json \
  --series "Realm of the Elderlings" --scenarios A C D
```

Inside the container:

```bash
docker compose -f docker-compose.dev.yml exec app \
  python -m src.literary.cli estimate --inventory /app/data/calibre/targets.json \
  --series "The Sun Eater" --scenarios A B C D
```

## 7. Uncertainty and what can change the bill

- **Tokenizer mismatch.** The model measures `cl100k_base`; Gemini, DeepSeek and
  Qwen use different tokenizers. Expect ±20–30% on token counts until measured
  with the provider's usage fields.
- **Chunk size.** 450 tokens is the upstream default; larger chunks reduce
  prompt overhead but may increase output cost and context risk.
- **Context.** 50 tokens of previous context is the upstream default. A
  chapter-summary or full-document context raises input cost sharply.
- **Glossary/style.** A 900-token glossary block on every chunk is a real cost;
  the context-rich table shows it.
- **Retries.** The default is 10%; malformed placeholders can push it higher.
  A 25% retry rate is the conservative column.
- **Cache.** DeepSeek/Gemini/OpenAI cache discounts depend on stable prefixes
  and provider behaviour. The model assumes 75% of the stable prompt is cached;
  the conservative column disables that.
- **Batch.** 50% is documented for Gemini and OpenAI; DeepSeek has no batch
  discount, only off-peak.
- **Price changes.** Gemini 3.8 Flash doubles on 2027-01-01; Gemini 4 Argon
  doubles on 2026-12-01. Re-check before spending.
- **Human review.** Not included. Budget it separately; it dominates.
- **Local electricity/hardware.** Not included. The RTX 4060 system draws
  roughly 200 W under load; at 20 hours and a local tariff, the electricity is
  a few dollars, not a per-token cost. The card is already owned.

## 8. Budget policy

- The cost preview is a **gate**, not a suggestion: store
  `estimated_cost`, set `max_budget_usd`, and refuse the next chapter when
  `actual_cost` reaches the cap.
- Log actual prompt/completion tokens and provider-reported cost per request.
- Re-estimate after the first 5% of a book and replace the initial estimate
  with the measured rate.
- Never use key rotation to continue after a provider limit; stop and ask.
- No cloud spend without explicit approval; the default provider is local.
