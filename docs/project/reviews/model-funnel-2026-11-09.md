# Model funnel — candidates for the 8 GB card

Desk check on 2026-11-09. No candidate was downloaded or installed.

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

## Recommended order

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

## Not yet verified

- Exact Q4_K_M file sizes and Ollama import behavior.
- Whether Seed-X's OpenMDW terms fit the intended publication.
- Whether Tower's 2048-token training context is sufficient for chapter work.
- Per-model VRAM peaks; the current Fase D VRAM number is an aggregate.
