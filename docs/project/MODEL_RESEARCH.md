# Model research: local and cloud candidates

Checked on **2026-11-07**. Prices are USD per one million tokens unless stated.
This document separates:

- **FACT** — stated in an official model card, paper, pricing page, or measured
  locally;
- **INDEPENDENT** — a third-party evaluation, not the vendor;
- **INFERENCE** — a technical reading of the evidence;
- **HYPOTHESIS** — a claim that still needs the project's own PT-BR benchmark.

No cloud API was called and no large model was downloaded for this audit. The
only local generations were produced with models already installed by the user.

## 1. What “best” means here

A model that wins a sentence-level WMT benchmark is not automatically the best
engine for a 300,000-word novel. The relevant axes are:

1. semantic fidelity and resistance to omission/invention;
2. natural Brazilian Portuguese prose and voice;
3. instruction-following under a glossary and a style block;
4. behaviour at the context sizes a chapter actually needs;
5. stability over thousands of chunks (no drift, loops, truncation);
6. licence, privacy, hardware fit and cost.

A specialized translation model with a rigid 2K-token prompt can be excellent
on a paragraph and unusable as the main engine. That distinction drives the
recommendation.

## 2. Local models

### 2.1 TranslateGemma 12B

| Item | Value |
|---|---|
| Model | `google/translategemma-12b-it` |
| Family | TranslateGemma 4B / 12B / 27B, built on Gemma 3 |
| Languages | 55, including Portuguese (Brazil) `pt-BR` |
| Context | **~2K tokens** is the optimized regime; Ollama exposes 128K because it is Gemma 3, but the model card/vLLM recipe says the model is optimized for about 2K |
| Prompt | One user message with a fixed professional-translator template; two blank lines before the text |
| Licence | Gemma Terms of Use; gated on Hugging Face |
| Local format | Ollama `translategemma:12b`, 8.1 GB, Q4_K_M |
| Reported metrics | WMT24++ MetricX 3.60, COMET 83.5; WMT25 MQM 7.94 on 10 pairs; 12B beats Gemma 3 27B on the automatic metric |
| Evidence level | Vendor model card + technical report; independent human evaluation is more mixed than the headline |

Official sources:
- <https://huggingface.co/google/translategemma-12b-it>
- <https://blog.google/innovation-and-ai/technology/developers-tools/translategemma>
- <https://arxiv.org/abs/2601.09012>
- vLLM recipe: <https://github.com/vllm-project/recipes/blob/main/Google/TranslateGemma.md>

**Local observation (FACT).** On the RTX 4060, a 500-character dialogue excerpt
took 23–66 seconds (the first run includes model load). The model produced
fluent Portuguese, but in the pilot it translated “This pup’s for you” as
“Este pedaço de pão é para você” (the puppy became bread), changed the male
narrator to “nua” in a Sun Eater passage, and invented fauna names
(“corujas-de-bico”, “lagartos-ferrugem”) for roadrunners and stinging lizards.
These are critical semantic errors, not style preferences.

**INFERENCE.** TranslateGemma is a strong short-passage translator. It is not a
good primary engine for a long novel: the 2K regime cannot hold a chapter, the
fixed prompt has little room for a glossary/style block, and the observed
failure mode is confident invention. It is a candidate for short passages,
image text, or a first draft that a source-aware reviewer will check.

### 2.2 Tencent Hy-MT2 7B

| Item | Value |
|---|---|
| Model | `tencent/Hy-MT2-7B` |
| Family | 1.8B / 7B / 30B-A3B; 33 languages including Portuguese |
| Context | Config allows 262,144, but the practical serving guidance is ~8,192 tokens; do not assume 262K |
| Prompt | No default system prompt; instruction-style user prompt, full language names |
| Licence | Apache-2.0 |
| Local format | Official GGUF; Q4_K_M is about 4.4 GB |
| Reported metrics | FLORES-200 XCOMET-XXL 86.89; WMT25 63.86 / 71.21 / 82.24; IFMTBench 83.14; vendor says it beats DeepSeek-V4-Pro and Kimi K2.6 in fast-thinking mode |
| Evidence level | Vendor paper + model card; WMT26 video-subtitle teams independently used Hy-MT2-7B successfully |

Official sources:
- <https://huggingface.co/tencent/Hy-MT2-7B>
- <https://arxiv.org/abs/2605.22064>
- <https://github.com/Tencent-Hunyuan/Hy-MT2>

**Why it matters.** 7B dense, Apache-2.0, fits an 8 GB card at Q4, supports
instruction-following and terminology/style constraints, and has a realistic
8K working context. It is the most plausible local primary engine on paper.
It is **not installed**; testing requires a download approval.

### 2.3 Index-Translate 9B

| Item | Value |
|---|---|
| Model | `IndexTeam/Index-Translate-9B` / `Index-Translate-9B-GGUF` |
| Family | 2B / 9B / 35B-A3B; Qwen3.5-based |
| Languages | 150 |
| Context | 16,384 tokens used in the main evaluation; 32,768 serving preset; config max 262,144 |
| Prompt | Chinese-centric translation/instTrans template; English instructions may work but must be tested |
| Licence | Apache-2.0 |
| Local format | Official GGUF; Q4_K_M 5.78 GB |
| Reported metrics | FLORES COMET-22 0.8789; WMT26 Judge 75.35; instTrans IFscore 0.8209; strong terminology hard constraints |
| Evidence level | Vendor paper/model card; no independent literary PT-BR study found |

Official sources:
- <https://huggingface.co/IndexTeam/Index-Translate-9B>
- <https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF>
- <https://arxiv.org/abs/2609.40181>

**Why it matters.** It explicitly supports hard glossary constraints, format
preservation and instruction-following, and it has a real long-document
specialist in the same family (`Index-NativeLong`, separate model). It is a
strong candidate for the glossary-heavy workflow. Risks: the prompt format is
Chinese-centric, the model is optimized for general translation rather than
literary voice, and 5.78 GB weights + KV cache is tight on 8 GB at 8K context.
It is **not installed**.

### 2.4 Installed generalists (pilot evidence)

| Model | Weights | Practical context | Pilot observation |
|---|---:|---:|---|
| Qwen3 8B Q4 | 5.2 GB | 8K | Best throughput/quality among installed models; correct “pup”, correct male narrator; but omitted a long clause and mistranslated regional fauna/objects |
| Qwen3 14B Q4 | 9.3 GB | 8K (offload) | Better on long syntax and some imagery; still reversed “turned away from me” and garbled a “man-sized portion” phrase; 45–86 s per excerpt |
| Qwen3.5 4B | 3.4 GB | 8K | Fast pipeline smoke test; not a literary candidate |
| TranslateGemma 12B | 8.1 GB | ~2K | Fluent but critical hallucinations; not a primary novel engine |

**INFERENCE.** For the installed set, Qwen3 8B is the best baseline to compare
against the specialized models. Qwen3 14B is not a clear enough quality jump to
justify its speed penalty without a larger benchmark.

### 2.5 Other local options considered

- **Gemma 4 31B / larger generalists**: likely better prose, but 17 GB+ at Q4
  and far outside the 8 GB card; offloading would be slow and less stable.
- **Mistral Small/Medium, Tower+, Aya Expanse**: plausible multilingual
  generalists, but no PT-BR literary evidence and no installed weights.
- **NLLB-200 / M2M-100**: dedicated MT, but no instruction-following, no
  glossary/style control, and usually weaker literary prose. Not suitable as
  the main engine.
- **Fine-tunes of Hy-MT2/Qwen for PT-BR**: promising later, but a fine-tune
  needs a licensed parallel corpus and a proper evaluation; out of scope for
  the first production pass.

### 2.6 VRAM reality check

Weights alone are not the memory requirement. The KV cache grows with context:

```
KV bytes/token ≈ 2 × layers × kv_heads × head_dim × bytes_per_element
```

Approximate examples (Q4 weights, FP16 KV, 2 bytes/element):

| Model | Approx. KV/token | 4K context | 8K context | Weights | 8K total |
|---|---:|---:|---:|---:|---:|
| Qwen3 8B | ~0.15 MB | ~0.6 GB | ~1.2 GB | 5.2 GB | ~6.4 GB |
| Hy-MT2 7B | ~0.13 MB | ~0.5 GB | ~1.1 GB | ~4.4 GB | ~5.5 GB |
| Index-Translate 9B | ~0.26 MB | ~1.1 GB | ~2.1 GB | 5.78 GB | ~7.9 GB (tight) |
| TranslateGemma 12B | ~0.39 MB | ~1.6 GB | ~3.1 GB | 8.1 GB | >11 GB (offload) |

These are approximations, not a substitute for measuring the actual runtime.
They explain why TranslateGemma 12B offloads and why Index-Translate 9B should
be tested at 4K before 8K.

## 3. Cloud models

All prices are official list prices checked on 2026-11-07. Batch and cache
discounts are noted only where the provider documents them.

### 3.1 Google Gemini

| Model ID | Input | Output | Cache read | Batch | Context | Notes |
|---|---:|---:|---:|---:|---:|---|
| `gemini-3.8-flash` | $0.75 | $3.75 | $0.075 | 50% | 1M | Promo through 2026-12-31; doubles on 2027-01-01 |
| `gemini-3.5-flash-lite` | $0.30 | $2.50 | $0.03 | 50% | 1M | Cheaper, lower quality |
| `gemini-2.5-flash-lite` | $0.10 | $0.40 | $0.01 | 50% | 1M | Deprecated; routes to 3.5 Flash-Lite on 2026-12-01 |
| `gemini-3-flash-preview` | $0.50 | $3.00 | $0.05 | 50% | 1M | Preview; verify availability |
| `gemini-4-argon` | $2.00 → $4.00 | $10.00 → $20.00 | $0.10 → $0.20 | 50% | 1M | Introductory price ends 2026-11-30 |

Official: <https://ai.google.dev/gemini-api/docs/pricing>

**Privacy (FACT).** Paid Gemini API content is not used to improve Google
products. Logs are retained for up to 55 days by default and can be set to
7/14/28/55 days; free-tier content may be used to improve products.
Source: <https://ai.google.dev/gemini-api/docs/logs-policy>

**Independent evidence.** A public BookTrans English→Russian literary
“trap-point” benchmark (2026-09-23) ranked Gemini 3.8 Flash first at 91/100,
GPT-6 Astra 90, GLM 5.3 86, DeepSeek V4.1 Flash 79, GPT-6 Luna 72 and Claude
Haiku 4.5 55. A separate literary ranking (2026-10-01) placed Gemini 3.8 Flash
second and noted it was the fastest of the eight models. These are directional
and not PT-BR; they are not a substitute for our own benchmark.

### 3.2 DeepSeek

| Model ID | Input peak / off-peak | Output peak / off-peak | Cache hit peak / off-peak | Context | Notes |
|---|---:|---:|---:|---:|---|
| `deepseek-flash` (V4.1 Flash 1017) | $0.30 / $0.15 | $1.20 / $0.60 | $0.006 / $0.003 | 1M | No batch discount; off-peak is 50% |
| `deepseek-v4-pro` | $1.32 / $0.66 | $3.96 / $1.98 | $0.044 / $0.022 | 1M | Being routed to V4.1 Flash in some periods; verify |

Official: <https://api-docs.deepseek.com/quick_start/pricing>

**Privacy (FACT, important).** DeepSeek's privacy policy and training-content
summaries allow user data to be used to train/improve models by default; there
is no published ZDR tier for the first-party API. The terms are a stack of
User Agreement + Privacy Policy + Open Platform Agreement. Do not send
copyrighted books to DeepSeek without explicit informed consent. This is a
first-order constraint, not a footnote.

Sources:
- <https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html>
- <https://cdn.deepseek.com/policies/DeepSeek-V4.1-public-summary-of-training-content.pdf>

### 3.3 OpenAI

| Model | Input | Output | Cache read | Batch | Context |
|---|---:|---:|---:|---:|---:|
| `gpt-6-luna` | $0.10 | $0.50 | $0.01 | 50% | 1.05M |
| `gpt-5.4-nano` | $0.20 | $1.25 | $0.02 | 50% | 1.05M |
| `gpt-5.4-mini` | $0.75 | $4.50 | $0.075 | 50% | 1.05M |
| `gpt-6.1-terra` | $1.00 | $5.00 | $0.05 | 50% | 1.05M |

Official: <https://platform.openai.com/docs/pricing>

**Privacy (FACT).** API data is not used for training by default; abuse logs
are retained for up to 30 days; Zero Data Retention is available for eligible
customers on supported endpoints.
Source: <https://platform.openai.com/docs/guides/your-data>

### 3.4 Anthropic and OpenRouter

| Model / route | Input | Output | Cache read | Context | Notes |
|---|---:|---:|---:|---:|---|
| `claude-haiku-5.5` (Anthropic) | $0.10 | $0.50 | $0.01 | 1M | No training on commercial API by default |
| `openrouter:google/gemini-3.8-flash` | $0.825 | $4.125 | $0.0825 | 1M | ~10% above direct Google price |
| `openrouter:deepseek/deepseek-v4.1-flash-1017` | $0.15 | $0.60 | $0.003 | 1M | Provider-dependent privacy |
| `openrouter:openai/gpt-6-luna` | $0.10 | $0.50 | $0.01 | 1.05M | Provider-dependent privacy |
| `openrouter:anthropic/claude-haiku-5.5` | $0.10 | $0.50 | $0.01 | 1M | Provider-dependent privacy |
| `openrouter:z-ai/glm-5.3` | $0.0699 | $1.40 | $0.0689 | 1M | Cheap input; output less cheap |
| `openrouter:minimax/minimax-m3.1-flash` | $0.075 | $0.30 | $0.0075 | 1M | Very cheap; quality unverified |
| `openrouter:qwen/qwen3.5-397b-a17b` | $0.50 | $3.60 | $0.30 | 262K | Large generalist |

OpenRouter models endpoint: <https://openrouter.ai/api/v1/models>.

**Privacy (FACT).** OpenRouter does not retain prompts by default unless
prompt logging is enabled. It exposes `zdr: true` and
`data_collection: deny` per request; ZDR-only routing restricts requests to
providers with a zero-retention policy. Provider policies differ, so an
aggregator is not automatically private.
Sources:
- <https://openrouter.ai/docs/guides/features/zdr>
- <https://openrouter.ai/docs/guides/privacy/provider-logging>

## 4. Price/quality reading

**FACT.** At the token level, the cheap cloud models are far cheaper than most
people expect: the measured 100k-word model in this project needs roughly
0.39M input and 0.19M output tokens for a single pass. At DeepSeek off-peak
prices that is about **$0.15 per 100k words**; Gemini 3.8 Flash is about
**$0.92 per 100k words**; GPT-6 Luna and Claude Haiku 5.5 are about
**$0.12 per 100k words** (see `COST_MODEL.md` for the full assumptions).

**INFERENCE.** Price alone does not decide. The expensive part of a serious
literary translation is human review, not the API bill. A model that saves
$20 on a saga but adds 30 hours of editorial repair is not cheaper.

**HYPOTHESIS.** The best economic architecture is likely hybrid: a cheap/local
first draft with strong glossary/style control, followed by selective
source-aware review by a stronger model on flagged segments. This must be
tested against a strong single-pass model; the ACL 2026 refinement study
suggests the gains are mostly fluency/style, not accuracy, so the reviewer must
see the source.

## 5. Provisional recommendation

### Local

1. **Test first:** Hy-MT2-7B (Apache-2.0, 8K, instruction/glossary support,
   4.4 GB Q4) and Index-Translate-9B (Apache-2.0, glossary hard constraints,
   5.78 GB Q4). Neither is installed; download requires approval.
2. **Installed baseline:** Qwen3 8B. Use it to calibrate prompts and
   throughput; do not treat it as the final literary engine.
3. **Quality check:** Qwen3 14B. It improves some long-syntax cases but is
   much slower and still makes critical errors.
4. **Not as primary:** TranslateGemma 12B. Use for short passages or as a
   drafting aid, never as the sole engine for a novel.
5. **Final local winner:** unknown until the Phase 4 benchmark with the same
   corpus, glossary and style controls. Do not select by parameter count.

### Cloud

1. **Quality-first provisional:** Gemini 3.8 Flash. Best independent literary
   evidence among the current cheap models; paid-tier privacy is acceptable;
   50% batch and context caching help.
2. **Cost-first provisional:** DeepSeek V4.1 Flash (`deepseek-flash`). Very
   cheap, 1M context, strong general capability, but the privacy policy is a
   blocker for copyrighted books unless the user explicitly accepts it or uses
   a provider route with ZDR/contractual guarantees.
3. **Cheap challengers:** GPT-6 Luna and Claude Haiku 5.5. Both are priced like
   DeepSeek Flash but have clearer no-training defaults; their PT-BR literary
   quality is unverified.
4. **Mid-tier challenger:** GPT-6.1 Terra ($1/$5) and GLM 5.3 (cheap input,
   $1.40 output) deserve a PT-BR test if the cheap tier fails the rubric.
5. **Aggregators:** use only with `zdr: true` and `data_collection: deny`; do
   not assume the aggregator's privacy is the provider's privacy.

### What would change the recommendation

- A PT-BR literary benchmark showing Hy-MT2-7B or Index-Translate-9B preserves
  voice and terminology better than Qwen3 8B/14B.
- A cloud test showing Gemini 3.8 Flash's independent lead does not transfer to
  PT-BR, or that a cheaper model is within the rubric's confidence interval.
- A privacy decision that rules out DeepSeek/OpenRouter providers.
- A measured human-review cost that makes a more expensive model cheaper per
  accepted chapter.

## 6. Sources

Primary model and pricing sources are linked in the tables above. The main
independent/contextual sources used here:

- TranslateGemma model card: <https://huggingface.co/google/translategemma-12b-it>
- TranslateGemma technical report: <https://arxiv.org/abs/2601.09012>
- Hy-MT2 model card: <https://huggingface.co/tencent/Hy-MT2-7B>
- Hy-MT2 paper: <https://arxiv.org/abs/2605.22064>
- Index-Translate model card: <https://huggingface.co/IndexTeam/Index-Translate-9B>
- Index-Translate paper: <https://arxiv.org/abs/2609.40181>
- Gemini pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini logs policy: <https://ai.google.dev/gemini-api/docs/logs-policy>
- DeepSeek pricing: <https://api-docs.deepseek.com/quick_start/pricing>
- DeepSeek privacy policy: <https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html>
- DeepSeek V4.1 training-content summary: <https://cdn.deepseek.com/policies/DeepSeek-V4.1-public-summary-of-training-content.pdf>
- OpenAI pricing: <https://platform.openai.com/docs/pricing>
- OpenAI data controls: <https://platform.openai.com/docs/guides/your-data>
- OpenRouter models: <https://openrouter.ai/api/v1/models>
- OpenRouter ZDR: <https://openrouter.ai/docs/guides/features/zdr>
- OpenRouter provider logging: <https://openrouter.ai/docs/guides/privacy/provider-logging>
- BookTrans EN→RU literary trap benchmark (2026-09-23): <https://ai-digest-1.com/news/benchmark-of-english-to-russian-translation-quality-for-leading-western-and-chin-13689>
- Independent literary ranking (2026-10-01): <https://dev.to/bozhidar_valchev/in-search-of-the-best-ai-literary-translator-detailed-30pk>
- Document-level literary refinement study (ACL 2026): <https://aclanthology.org/2026.acl-long.268/>
- WMT26 general MT findings: <https://aclanthology.org/2026.wmt-main.48.pdf>
- Literary MT evaluation with humans and LLMs: <https://arxiv.org/html/2410.18697v2>

## 7. Open questions

1. How do the models handle **Brazilian Portuguese** specifically, not Portuguese
   in general? `pt-BR` vs `pt-PT` is a real register/lexicon difference.
2. How much glossary/style instruction can each model follow before its
   translation quality degrades?
3. How do they behave at 4K, 8K and 16K contexts on consecutive chapters, not
   isolated paragraphs?
4. What is the actual omission/repetition rate over 50+ consecutive chunks?
5. How do provider tokenizers count Portuguese output versus `cl100k_base`?
6. What are the current rate limits, data-retention terms and deprecation dates
   at the moment of purchase? Re-check before spending.
