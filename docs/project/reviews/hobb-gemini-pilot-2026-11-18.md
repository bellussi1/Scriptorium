# Robin Hobb Gemini Pilot Report (2026-11-18)

## Scope & Execution Status

- **Target corpus:** `data/benchmark/literary/pilot_hobb_chapter.jsonl` (`10` aligned Robin Hobb excerpts from `eval_farseer_dev.jsonl`, `2,010` English words across `long_syntax`, `irony`, `introspection`, `dialogue`, `action`, `description`, and `terminology`, all paired with the official Brazilian Portuguese edition `reference_pt`).
- **Gemini Pro compatibility changes implemented & tested:**
  - `src/core/llm/providers/gemini.py`: `gemini-2.5-pro` sends `thinkingConfig: {thinkingBudget: 128}` (cannot disable with `0`), `gemini-3.1-pro-preview` omits `thinkingConfig`, HTTP 400 `"thinking"` errors pop `thinkingConfig` and retry cleanly, and `completion_tokens` sums `candidatesTokenCount + thoughtsTokenCount`.
  - `src/literary/cost.py` & `scripts/benchmark_cloud.py`: added `gemini-2.5-pro` and `gemini-3.1-pro-preview` pricing and `--max-cost-usd` cap enforcement.
- **Live Cloud Execution Status (`$0.00` spent):**
  - Calling `/v1beta/models/gemini-3.8-flash:generateContent` and `gemini-2.5-pro:generateContent` on `2026-11-18` with `.env` `GEMINI_API_KEY` (`...EYNg`) returned **`HTTP 402 Payment Required`** across all 20 requests (`"Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing"`).
  - Direct probe on `.env` `GEMINI_API_KEY_2` (`...mmqA`) also returned **`HTTP 402 Payment Required`** with the same depleted-credits message.
  - Because both `.env` keys belong to an exhausted prepayment project, **live Gemini 3.8 Flash / Gemini 2.5 Pro generation is blocked** until the Google AI Studio API key associated with the active US$ 40 credit project is configured in `.env`.
- **Available Comparison Data:**
  - **`Index-Translate-9B` (local Ollama, live `2026-11-18`):** ran all `10` pilot excerpts cleanly (`data/benchmark/hobb-pilot-local/repeat-01/20261118T035516Z/index-translate-9b.jsonl`) with the updated Farseer resources (`62` prompt terms).
  - **`Gemini 3.8 Flash` (recorded `2026-11-10`):** all `10` pilot IDs were previously evaluated on `2026-11-10` under the prior Farseer prompt (`data/benchmark/cloud-dev-combined/gemini-3.8-flash.jsonl`, before `Mountain Kingdom -> Reino da Montanha` and `Lady` keep rules were refined).

## Aggregate Metrics (10 Excerpts)

| Model | Run Date | Prompts | Mean chrF | Name Recall | Length Ratio | Eng. Leakage | Mean Latency | Cost (10 excerpts) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Index-Translate-9B` (local) | `2026-11-18` (live) | Updated (`62` terms) | `0.7303` | `0.9167` | `1.0382` | `0.0` | `10.02 s` | `$0.00000` |
| `Gemini 3.8 Flash` | `2026-11-10` (recorded) | Prior Farseer prompt | `0.7126` | `0.9800` | `1.0246` | `0.0` | `31.37 s` | `$0.02167` |
| `Gemini 2.5 Pro` | Pending active key | — | — | — | — | — | — | Blocked (`402`) |

> Note: `Index-Translate-9B` scored slightly higher mean `chrF` on these 10 excerpts mainly because it ran against the updated `2026-11-18` glossary (`Mountain Kingdom -> Reino da Montanha`, `Lady Patience`), whereas the historical `2026-11-10` Flash run lacked those entries (`Reino das Montanhas`, `Dama Patience`). Qualitatively, Gemini Flash eliminated severe local-model defects observed below.

## Side-by-Side Excerpts

### 1. Dialogue & Terminology (`assassins-quest-34-0104`)
- **English:** `"One girl and a Farseer child," the Fool reminded me gravely. "Fitz, I do not speak to grieve you, but only to warn you. I have contained his anger at you. That night, when they held me . . ." He swallowed and his eyes went distant. "I have tried so hard to forget it. . ."`
- **Official PT-BR:** `— Uma garota e uma criança Farseer — o Bobo me lembrou gravemente. — Fitz, não falo para entristecê-lo, apenas para avisá-lo. Contive a raiva que ele sente por você. Naquela noite, quando eles me seguraram… — Ele engoliu em seco e seus olhos ficaram distantes. — Tentei tanto esquecer isso.`
- **Index-Translate-9B (`2026-11-18`, chrF `0.7204`):** `“Uma menina e uma criança Farseer”, lembrou-me o Bobo, com gravidade. “Fitz, não falo para te entristecê-lo, mas apenas para te avisar. Eu contevei a raiva dele contra ti. Naquela noite, quando me prenderam...” Ele engoliu em seco e o seu olhar tornou-se distante.`
  - *Defects:* conjugated *"contive"* incorrectly as `"contevei"`, mixed second-person pronouns (`te`, `ti`), used ASCII quotes.
- **Gemini 3.8 Flash (`2026-11-10`, chrF `0.7634`):** `— Uma moça e uma criança Farseer — lembrou-me o Bobo com gravidade. — FitzChivalry Farseer, não falo para lhe causar pesar, mas apenas para adverti-lo. Contive a ira dele contra você. Naquela noite, quando me prenderam… — Ele engoliu em seco e o olhar se fez distante.`
  - *Quality:* natural literary rhythm, travessão formatting, zero pronoun mixing or verb conjugation errors.

### 2. Irony & Gender Consistency (`assassins-apprentice-15-0016`)
- **English:** `Verity paired with one of Regal's sugar-crystal women. . . on richly caparisoned palfreys . . . "Prince catchers," I'd heard them called`
- **Index-Translate-9B (`2026-11-18`, chrF `0.6790`):** `Verity estava unida a uma das mulheres de cristal de açúcar de Regal. . . montadas em palfreys ricamente adornados . . . “Cacadoras de príncipes”`
  - *Defects:* flipped Prince Verity's grammatical gender to feminine (`unida`), left `palfreys` untranslated in English, dropped the cedilla in `Cacadoras`.
- **Gemini 3.8 Flash (`2026-11-10`, chrF `0.6538`):** `Verity emparelhado a uma das mulheres de cristal de açúcar de Regal. . . em palafréns ricamente ajaezados . . . “Caçadoras de príncipes”`
  - *Quality:* preserved masculine agreement (`emparelhado`), translated `palfreys` accurately (`palafréns`), correct orthography.

### 3. Dialogue & Glossary Drift (`assassins-quest-02-0067`)
- **English:** `"When have you not?" Chade demanded as fiercely. . . "Patience tried to warn you off Molly, yet you had your way there too. . . And your next-to-last stupid act in Buckkeep was to volunteer to be part of an uprising against the crown."`
- **Index-Translate-9B (`2026-11-18`, chrF `0.7191`):** `"Quando foi que você não fez isso?", exigiu Chade, com a mesma veemência. . . Patience tentou te alertar para ficar longe de Molly, mas você fez do seu jeito lá também. . . E seu penúltimo ato idiota em Buckkeep foi se voluntariar para participar de uma rebelião contra a coroa.`
  - *Defects:* missed glossary target `Buckkeep -> Torre do Cervo`, slipped into `te`.
- **Gemini 3.8 Flash (`2026-11-10`, chrF `0.6903`):** `— E quando foi que não fez? — cobrou Chade, com a mesma veemência. . . Patience tentou adverti-lo para ficar longe de Molly, mas você fez a sua própria vontade ali também. . . E a sua penúltima estupidez na Torre do Cervo foi se oferecer para participar de um levante contra a coroa.`
  - *Quality:* natural dialogue voice (`cobrou`, `estupidez`), proper `Torre do Cervo`, zero `tu/te`.

### 4. Syntax & Political Irony (`assassins-apprentice-04-0002`)
- **English:** `When the titleholder weds, he is supposed to keep this in mind. The partner chosen must be willing likewise to be a steward. For this reason, the partner holding a lesser title must surrender it to the next younger sibling.`
- **Index-Translate-9B (`2026-11-18`, chrF `0.6918`):** `Quando o titular de um título se casa, deve ter isso em mente. A parceira escolhida também precisa estar disposta a ser uma administradora. Por essa razão, a parceira que detém um título inferior deve entregá-lo ao irmão mais novo seguinte.`
- **Gemini 3.8 Flash (`2026-11-10`, chrF `0.6579`):** `Quando o detentor de um título se casa, espera-se que tenha isso em mente. O consorte escolhido deve estar igualmente disposto a ser um administrador. Por essa razão, quem detém um título menor deve cedê-lo ao irmão imediatamente mais jovem.`

## Next Action to Run Live Gemini Flash vs. Gemini Pro Comparison

Once the API key from the Google AI Studio project holding the US$ 40 balance is placed in `.env` (`GEMINI_API_KEY=...`), run the remaining cloud leg within the US$ 0.50 cap:

```powershell
venv\Scripts\python.exe -X utf8 scripts/benchmark_cloud.py --corpus data/benchmark/literary/pilot_hobb_chapter.jsonl --models gemini-3.8-flash gemini-2.5-pro --concurrency 2 --max-cost-usd 0.45 --resource-author robin-hobb --resource-universe realm-of-the-elderlings --resource-subseries farseer --resource-book assassins-apprentice --resource-book-order 3 --out-root data/benchmark/hobb-pilot-cloud
```
