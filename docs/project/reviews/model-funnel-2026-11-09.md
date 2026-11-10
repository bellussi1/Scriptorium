# Model funnel — candidates for the 8 GB card

Desk check on 2026-11-09, followed by a five-excerpt smoke on SalamandraTA and
EuroLLM. The local decision is in
[`model-selection-2026-11-09.md`](model-selection-2026-11-09.md).

## Gate

1. GGUF Q4_K_M/Q5_K_M exists and is loadable by Ollama.
2. License allows the intended use (personal vs published translation).
3. Portuguese is in the model card's supported languages.
4. Context and weights fit the 8 GB card without silent offload.
5. Five-excerpt smoke before the full matrix.

## Candidates

| Model | Params | GGUF | License | PT | Note |
|---|---:|---|---|---|---|
| Salamandra-7B-Instruct | 7B | yes | Apache-2.0 | yes | Iberian-focused; best license/VRAM fit |
| EuroLLM-9B-Instruct | 9B | yes | Apache-2.0 | yes | 9B at the 8 GB edge; verify offload |
| Seed-X-PPO-7B | 7B | yes | OpenMDW | yes | Translation-specific; needs `<pt>` prompt, not chat |
| GemmaX2-28-9B-v0.1 | 9B | yes | Gemma | yes | Translation-specific; 9B at the edge |
| TranslateGemma-12B-IT | 12B | yes | Gemma | yes | Likely offload; only if 7–9B fail |
| TowerInstruct-7B-v0.2 | 7B | yes | CC-BY-NC-4.0 | yes | Non-commercial; document-level training max 2048 |
| Aya Expanse 8B | 8B | yes | CC-BY-NC-4.0 | yes | Non-commercial; strong multilingual |

The current production models (Hy-MT2 Q4 and Index-Translate 9B) are
Apache-2.0. Tower and Aya are a licensing downgrade unless the books are
strictly personal.

## Pre-smoke order (historical)

1. **Salamandra-7B-Instruct** — Apache-2.0, 7B, Portuguese-focused.
2. **Seed-X-PPO-7B** — translation-specific, 7B, but the prompt must use the
   `<pt>` tag and the model is not a chat model.
3. **EuroLLM-9B-Instruct** — Apache-2.0, 9B; only if the two 7B candidates do
   not beat Q4/Index.
4. **GemmaX2-28-9B-v0.1** — translation-specific, Gemma license; 9B.
5. **TranslateGemma-12B-IT** — park unless the smaller candidates fail.

Download at most two at a time. Smoke five excerpts; if a model does not beat
the current pair on terminology/name gates and blind prose, uninstall it. Do not
run a 12B model “just to see”.

## Verification update (2026-11-09, after desk check)

The first table mixed the base Salamandra model with the translation variant.
The current facts are:

| Candidate | GGUF | License | PT | Practical note |
|---|---|---|---|---|
| SalamandraTA-7B-instruct v3 | official Q4_K_M, 4.85 GB | **GPL-3.0** | 40 languages | Translation-only, no chat; the base Salamandra-7B-Instruct is Apache-2.0 but is not the translation-tuned model. GPL is a distribution constraint. |
| Seed-X-PPO-7B | unofficial Q4_K_M, 4.56 GB | OpenMDW | 28 languages | No chat template; prompt must end with `<pt>`; model card recommends beam search and warns against unofficial quants. |
| EuroLLM-9B-Instruct | official-style Q4_K_M, 5.58 GB | Apache-2.0 | 35 languages | ChatML template; fits the 8 GB card at 8K with little headroom. |
| GemmaX2-28-9B-v0.2 | no official GGUF; third-party quants | Gemma | 28 languages | Translation-only; official weights are safetensors. |

The cleanest license/GGUF combination is **EuroLLM-9B-Instruct**. Seed-X is
the most interesting translation specialist but carries the unofficial-quant
and no-chat-template risks. SalamandraTA is the strongest Iberian-focused
option but its GPL-3.0 license has to be accepted before use.

WMT25 preliminary automatic rankings include EuroLLM-9B and SalamandraTA for
some pairs, but English-Portuguese is not in that WMT25 table, so those ranks
are not evidence for this decision.

## Smoke results (2026-11-09)

- **SalamandraTA-7B-instruct v3:** native ChatML prompt, five excerpts, mean
  chrF 0.6729 (Index 0.6726, Q4 0.6543 on the same five). But the production
  glossary/style prompt caused runaway continuation (length ratios 5.3–15.1,
  mean chrF 0.0883) and the native output translated "Chivalry" as
  "a cavalaria". Rejected for the queue; needs a dedicated adapter and a much
  smaller glossary block before another attempt.
- **EuroLLM-9B-Instruct:** five dialogue excerpts with the production
  glossary/style prompt, mean chrF 0.6870 (Index 0.6971, Q4 0.6634 on the same
  five), latency 1.5–5.6 s. It keeps "Raiders"/"coterie" in English, writes
  Skill as "Habilidade", and uses European-Portuguese articles before names.
  Rejected at the terminology/pt-BR gate.
- **Seed-X-PPO-7B:** reserve; not integrated.

## Not yet verified

- Exact Q4_K_M file sizes and Ollama import behavior.
- Whether Seed-X's OpenMDW terms fit the intended publication.
- Whether Tower's 2048-token training context is sufficient for chapter work.
- Per-model VRAM peaks; the current Fase D VRAM number is an aggregate.
