# Editorial Profiles: Lonesome Dove, Realm of the Elderlings, Sun Eater

## 1. Purpose and scope

This brief records the evidence behind eight style resources for English-to-Brazilian-Portuguese literary translation:

- one book profile for *Lonesome Dove*;
- one universe base and five subseries profiles for *Realm of the Elderlings*;
- one series profile for *Sun Eater*.

The profiles describe prose tendencies, not terminology. Names, invented terms, titles, and institutional vocabulary belong to the glossary module and are deliberately not settled here. I did not modify any file under `src/`. The Calibre library was read-only throughout. No paid API was called.

The resources are written for the repository's existing style schema: `mode`, `context`, `rules`, and `description`, with `evidence` and `notes` kept as metadata. The upstream dimension list in `src/core/style/dimensions.py` calls paragraph-level formatting `formatting`; it does not contain a separate `paragraphing` value. Paragraph rules therefore use `formatting`, and `other` is used only where the effect is not strictly typographic. The instruction text still carries the paragraph-level guidance.

## 2. Method

### 2.1 Samples

The local corpus contains the first three long spine documents of each available edition. The manifests record roughly 1,700 to 9,700 words per document. I read the first chapter of every edition in full and substantial passages from chapters two and three, with targeted re-reading where the English and Portuguese texts could be compared.

The comparison set is uneven:

- **Aligned English/Portuguese pairs:** *Lonesome Dove*, *Assassin's Apprentice*, and *Royal Assassin*.
- **English only:** *Howling Dark* and *Demon in White*.
- **Portuguese only:** *Império do Silêncio*, the translation of the first *Sun Eater* book.

The *Sun Eater* Portuguese comparison is therefore cross-book. It can describe translation strategy and register, but it cannot measure sentence-level equivalence between an English source and its Portuguese rendering. The *Royal Assassin* sample opens with the prologue, not chapter one; its prose is more essayistic than the novel's action chapters, and the sample metrics reflect that.

The local Portuguese files are valid UTF-8. Some terminal and review panes render the em dash (U+2014) and accented characters as replacement glyphs, which made an earlier draft suspect an encoding fault; byte-level inspection confirmed the underlying text is correct. The travessão is real, not mojibake. Lexical counts are therefore reliable, subject to the usual limits of a three-chapter sample.

### 2.2 Measurements

Counts were made with `scripts/literary/style_metrics.py` and `scripts/literary/style_markers.py` over the local samples. A paragraph is a non-empty line; the EPUB extraction preserves paragraph breaks as line breaks. A sentence ends at terminal punctuation followed by a capital letter, a quotation mark, or a digit. A dialogue paragraph is a line that begins with a quotation mark or a Portuguese travessão. P90 is the 90th percentile of sentence length in words. These rules are simple and consistent across editions; they are not a linguistic parser. Chapter headings and running titles are counted as paragraphs, which slightly inflates the one-word and very-short paragraph counts. `scripts/literary/validate_styles.py` re-runs the upstream style lint and the resource compiler over every profile.

The full-book figures in Section 3.1 were supplied by the project's earlier measurement pass and are treated as the stable baseline. The three-chapter figures in Sections 3.2 to 3.5 were measured for this brief. They are useful for comparing editions under the same script, not for estimating the whole book.

Contraction counts cover English auxiliary and negative contractions. Portuguese has no direct equivalent, so the Portuguese contraction column is zero by construction and should not be read as a stylistic absence. Em-dash counts mix dialogue punctuation with asides; the Portuguese editions use the travessão for speech, which roughly doubles the dash count. The dash figures are therefore evidence about typographic convention, not about prose rhythm.

### 2.3 Labels

- **FACT** — measured, directly observed in the samples, or supplied by the project measurement pass.
- **INFERENCE** — a reading of the evidence that goes beyond the count but stays tied to observable features.
- **HYPOTHESIS** — a testable claim that the current sample cannot settle.
- **EDITORIAL DECISION** — a translation-policy choice made for this project, not a claim about the source.

### 2.4 Limitations

- **Three chapters, not the whole book.** The samples are long enough to characterize voice and scene rhythm, but not long enough to prove that a tendency holds across a 300,000-word novel.
- **Chapter one is not a random sample.** It carries more exposition, backstory, and framing than an average chapter. The full-book metrics are the better baseline.
- **The Portuguese comparison is partial.** Only three works have aligned English and Portuguese samples. The Sun Eater comparison is cross-book. The provisional Hobb subseries have no Portuguese sample at all.
- **The Portuguese comparanda are not one norm.** The samples mix Brazilian and European-leaning features. They are evidence of editorial choices, not a target standard.
- **Terminal rendering can misrepresent accents and the travessão.** Byte-level checks confirmed the Portuguese samples are valid UTF-8; this is a display issue, not damaged source text.
- **The metrics are shallow.** They count sentences, paragraphs, punctuation, and a keyword set of reporting verbs. They do not parse syntax, semantics, or discourse.
- **The provisional Hobb profiles are structural priors.** They are not close readings and should not be quoted as observations about the unsampled books.

## 3. Measurements

### 3.1 Full-book baseline (FACT, supplied)

| Work | Edition | Words | Mean sentence | Median | P90 | Dialogue paragraphs |
|---|---:|---:|---:|---:|---:|---:|
| *Lonesome Dove* | English | 365,575 | 15.34 | 14 | 27 | 0.542 |
| *Lonesome Dove* | Portuguese | 353,609 | 13.64 | 12 | 25 | 0.544 |
| *Assassin's Apprentice* | English | 165,049 | 14.16 | 12 | 26 | 0.346 |
| *Assassin's Apprentice* | Portuguese | 163,924 | 13.47 | 11 | 26 | 0.473 |
| *Royal Assassin* | English | 260,533 | 12.20 | 11 | 23 | 0.421 |
| *Royal Assassin* | Portuguese | 257,065 | 10.62 | 9 | 21 | 0.509 |
| *Howling Dark* | English | 264,961 | 13.25 | 11 | 27 | 0.344 |
| *Demon in White* | English | 295,868 | 13.64 | 11 | 28 | 0.361 |
| *Império do Silêncio* | Portuguese | 262,581 | 12.26 | 10 | 25 | 0.462 |

The paired figures show shorter mean and median sentences in all four pairs, and a higher dialogue-paragraph ratio in the Hobb pairs; Lonesome Dove is essentially unchanged. **INFERENCE.** The dialogue ratio is largely a formatting effect. The shorter means are more interesting, but they are edition-level aggregates and cannot tell us whether the translator split, merged, or rewrote individual sentences.

### 3.2 Three-chapter rhythm (FACT, measured)

| Edition | Words | Paragraphs | Mean sentence | Median | P90 | Dialogue paragraphs |
|---|---:|---:|---:|---:|---:|---:|
| *Lonesome Dove* EN | 14,424 | 231 | 17.70 | 16 | 32 | 0.45 |
| *Lonesome Dove* PT | 13,946 | 231 | 18.40 | 17 | 32 | 0.45 |
| *Assassin's Apprentice* EN | 23,506 | 404 | 14.27 | 13 | 27 | 0.28 |
| *Assassin's Apprentice* PT | 24,410 | 436 | 16.00 | 14 | 30 | 0.443 |
| *Royal Assassin* EN | 18,184 | 282 | 11.16 | 10 | 21 | 0.401 |
| *Royal Assassin* PT | 18,678 | 395 | 11.93 | 10 | 23 | 0.489 |
| *Howling Dark* EN | 13,828 | 301 | 13.28 | 11 | 26 | 0.432 |
| *Demon in White* EN | 11,268 | 251 | 13.84 | 11 | 27 | 0.418 |
| *Império do Silêncio* PT | 10,453 | 291 | 15.58 | 14 | 30 | 0.485 |

The sample means run higher than the full-book means for *Lonesome Dove* and *Assassin's Apprentice*. This is expected: the first chapters carry a large share of exposition and backstory, and the Portuguese formatting appears to give more speech turns their own paragraph. The sample is not a random sample of the book. The full-book figures remain the better guide to central tendency.

### 3.3 Orality and punctuation (FACT, measured)

| Edition | Contractions / 1k | Semicolons / 1k | Dashes / 1k | Short fragments | One-word paragraphs | Paragraphs ≤ 5 words |
|---|---:|---:|---:|---:|---:|---:|
| *Lonesome Dove* EN | 21.56 | 0.97 | 4.71 | 5.0% | 3 | 12 |
| *Lonesome Dove* PT | 0 | 1.08 | 21.87 | n/a | 3 | 8 |
| *Assassin's Apprentice* EN | 18.38 | 0.85 | 0.43 | 11.3% | 9 | 32 |
| *Assassin's Apprentice* PT | 0 | 0.61 | 16.14 | n/a | 4 | 40 |
| *Royal Assassin* EN | 16.72 | 0.77 | 0.44 | 15.5% | 8 | 24 |
| *Royal Assassin* PT | 0 | 0.80 | 19.70 | n/a | 5 | 39 |
| *Howling Dark* EN | 22.56 | 0.29 | 5.93 | 14.9% | 2 | 26 |
| *Demon in White* EN | 15.18 | 1.51 | 5.06 | 14.9% | 2 | 40 |
| *Império do Silêncio* PT | 0 | 1.24 | 27.65 | n/a | 5 | 41 |

The dash column for Portuguese is dominated by dialogue punctuation. It should not be used to argue that the Portuguese prose is more fragmentary or more interrupted than the English. The one-word and very short paragraph counts are more comparable, though Portuguese dialogue interjections inflate them slightly.

### 3.4 Speech tags (FACT, measured)

A keyword set of reporting verbs was counted; the figures are an approximation, not a parsed tag inventory.

| Edition | Counted tags | Share of *said* / *disse* |
|---|---:|---:|
| *Lonesome Dove* EN | 140 | 73.6% |
| *Lonesome Dove* PT | 127 | 76.4% |
| *Assassin's Apprentice* EN | 130 | 36.2% |
| *Assassin's Apprentice* PT | 106 | 54.7% |
| *Royal Assassin* EN | 114 | 33.3% |
| *Royal Assassin* PT | 79 | 57.0% |
| *Howling Dark* EN | 136 | 70.6% |
| *Demon in White* EN | 105 | 60.0% |

The English Hobb samples spread their reporting verbs more evenly, while the Portuguese concentrates on *disse*. This is an INFERENCE from the counted set: the Portuguese may simply be less tolerant of the more literary reporting verbs, or the translator may be normalizing them. The Lonesome Dove and Sun Eater samples are already *said*-dominant, so their profiles can safely ask for plain tags.

### 3.5 Portuguese variety markers (FACT, indicative)

| Edition | *a minha* | *minha* | *você* | *tu* | *pra* | Enclisis / 1k |
|---|---:|---:|---:|---:|---:|---:|
| *Lonesome Dove* PT | 1 | 4 | 68 | 0 | 0 | 5.16 |
| *Assassin's Apprentice* PT | 44 | 87 | 116 | 0 | 0 | 12.25 |
| *Royal Assassin* PT | 31 | 73 | 98 | 0 | 0 | 11.51 |
| *Império do Silêncio* PT | 11 | 52 | 30 | 0 | 0 | 3.83 |

**FACT.** These are crude markers, not a dialect test. They show that the Portuguese comparanda are not a single norm. **INFERENCE.** The Hobb samples have a high rate of preposed possessives and enclisis, consistent with European Portuguese. The Lonesome Dove sample is closer to Brazilian colloquial usage: *você* predominates, preposed possessives are almost absent, and *tu* does not occur. The Sun Eater sample is mixed but leans European in its pronominal syntax.

**EDITORIAL DECISION.** The target is Brazilian Portuguese. The published translations are evidence of editorial choices, not a normative standard. Do not copy European Portuguese morphology, enclisis, or preposed possessives merely because the comparandum uses them. Do not copy the absence of *pra* either: the Lonesome Dove translator's standard colloquialism is one valid solution, not the only one.

## 4. Lonesome Dove

### 4.1 What the prose does

**FACT.** The novel is third-person throughout the sample. It moves between omniscient summary, comic anecdote, and the unmarked interiority of a character. The narration uses contractions at a high rate (21.56 per 1,000 words) and sentence-initial conjunctions; the full-book mean sentence is 15.34 words, with a p90 of 27 and a long tail up to 72 words in the sample. Dialogue occupies 54.2% of paragraphs in the full book. The speech-tag set is dominated by *said*.

**FACT.** The sample's paragraph median is 40 words, but the distribution is wide: 12 paragraphs are five words or fewer, and the longest paragraphs exceed 140 words. Chapter one is a crowded ensemble scene; chapter two alternates a solitary night walk with a porch conversation; chapter three is a compressed life story delivered in summary. The prose changes register with each of these situations without announcing the change.

**INFERENCE.** The narrator is best understood as an oral historian with a long memory and a taste for deadpan causation. The comedy rarely depends on a punchline. It depends on the flat delivery of an absurd causal chain, on the gap between a character's self-image and the narrator's judgment, and on the accumulation of physical detail until the situation becomes ridiculous. The narration is not minimalist; it is paratactic and cumulative, with short sentences used as a brake rather than as the default.

**INFERENCE.** Free indirect thought is a structural resource, not an occasional trick. The narrator can report a character's judgment in the narrator's own voice, then slide into the character's idiom, then withdraw. This is why the prose can be both affectionate and unsentimental: the narrator knows the characters from inside and still refuses to flatter them.

**INFERENCE.** The regional dialect is carried mainly by syntax, address, and idiom in dialogue, and by a looser version of the same habits in narration. The narration itself is not written in phonetic dialect, but it is not neutral either. It shares the characters' contractions, their casual profanity, and their matter-of-fact approach to violence.

### 4.2 What the published Portuguese appears to preserve and change

**FACT.** The Portuguese sample keeps the comic architecture, the concrete imagery, the period setting, the measurements, and the Spanish loanwords. It keeps the narrator's affectionate irony and the free indirect movement between narration and character. It does not reproduce English contractions, which Portuguese cannot mirror directly, and it does not use phonetic misspelling for regional speech.

**FACT.** The Portuguese dialogue uses *você* and full *para* rather than *tu* or reduced *pra*. **INFERENCE.** It standardizes nonstandard English syntax into educated Brazilian colloquialism, sometimes makes an elliptical connective explicit, and occasionally chooses a low-frequency verb that shifts the emotional direction of a phrase. **FACT.** The local sample's sentence count is lower than the English (758 against 815), but the full-book mean is shorter in Portuguese; the sample is not representative enough to support a claim about a consistent splitting or merging policy.

**INFERENCE.** The published translation's main gain is readability: the Brazilian reader gets the comedy and the scene without decoding a foreign dialect. The main loss is the social distance between the narrator's idiom and the characters' speech. When every voice is rendered in the same educated colloquial register, the novel can sound more uniformly literate than it does in English.

**HYPOTHESIS.** A translation that preserves more nonstandard syntax in dialogue, while keeping the narration standard, will better preserve the novel's class and regional texture than one that standardizes both. This is testable by comparing aligned passages for vocatives, verb agreement, and sentence fragments. The current sample does not contain enough aligned dialect density to settle it.

### 4.3 Translation risks

**INFERENCE.** The first risk is dialect flattening. If the translation invents a Brazilian regional accent, it imports a different social geography. If it writes neutral Portuguese, it loses the oral texture. The profile's decision is to render dialect through syntax, address, and lexical choice, with no eye dialect and no imported regional stereotype.

**INFERENCE.** The second risk is over-explaining free indirect thought. Adding a thought tag, quotation marks, or an explanatory clause can turn a seamless slide into a reported statement. The profile asks the translator to leave the transitions unmarked where the source leaves them unmarked.

**INFERENCE.** The third risk is comic inflation. The narrator's deadpan depends on not signalling that a joke is coming. Adding intensifiers, exclamation marks, or explanatory asides can make the prose sound like a tall tale being performed rather than a world being reported.

**EDITORIAL DECISION.** Preserve period prejudice and coarse talk where the source has them, without sanitizing and without amplifying. This is not a licence to add slurs or to modernize them into different ones. The novel's racial and colonial language is part of its historical texture; the translation should neither clean it up for comfort nor turn it into a spectacle.

**EDITORIAL DECISION.** Keep the source's measurements and loanwords. Do not convert miles to kilometres or inches to centimetres unless the edition's wider policy requires it. Do not translate Spanish loanwords into Portuguese when the code-switching is part of the scene.

**EDITORIAL DECISION.** Do not imitate the Portuguese sample's added connectives or its occasional lexical drift. Use them as evidence of one editorial solution, not as a target. The profile's sentence-rhythm rule asks for cumulative sentences and short brakes, not for a particular average sentence length.

### 4.4 Profile rationale

The nine rules map to the observable tendencies:

- `narrative_voice` protects the oral omniscience and the free indirect blend.
- `register` protects the unsentimental, deadpan tone and the period-bound coarseness.
- `sentence_rhythm` protects the long cumulative sentence and the short brake.
- `formatting` protects the paragraph logic: attention, riff, scene shift, and the isolated short paragraph.
- `dialogue` protects regional syntax without phonetic caricature.
- `imagery` protects the homely, tactile comparison.
- `lexicon` protects concrete period vocabulary and measurements.
- `punctuation` protects the restrained dash and semicolon regime.
- `other` protects the continuity between narrator commentary and free indirect thought.

The profile deliberately does not specify a dialect region, a contraction policy, or a sentence-length target. Those are decisions for the book's editorial team, not properties of the source.

## 5. Realm of the Elderlings

### 5.1 Universe-level profile

**FACT.** The two sampled Farseer books are first-person retrospective narratives. The narrator is a writer as well as a participant: he frames recollection as written history, comments on the act of writing, and then yields to scene-level sensory immediacy. *Assassin's Apprentice* opens with a historiographic preface that becomes memoir; *Royal Assassin* opens with an essay on magic and then moves into a hallucinatory present. The prose is dense with subordinate clauses, sensory detail, and explicit acts of remembering.

**FACT.** The full-book metrics show a mean sentence of 14.16 in *Assassin's Apprentice* and 12.20 in *Royal Assassin*. The second book is shorter and more dialogue-driven. In the three-chapter sample, *Assassin's Apprentice* has a mean of 14.27, a dialogue-paragraph ratio of 0.28, and an 11.3% short-fragment share; *Royal Assassin* has a mean of 11.16, a dialogue ratio of 0.401, and a 15.5% fragment share. The second book's opening is a prologue, so the comparison is between a prologue and a chapter, not between two identical narrative situations.

**FACT.** The Portuguese editions raise the dialogue-paragraph ratio sharply: 0.473 against 0.346 in *Assassin's Apprentice*, and 0.509 against 0.421 in *Royal Assassin*. **INFERENCE.** This is largely a formatting effect, consistent with the Portuguese editions giving more speech turns their own paragraph. The full-book Portuguese means are shorter than the English means in both books. The sample means are longer for *Assassin's Apprentice*, which is a reminder that chapter-level samples can reverse the aggregate.

**INFERENCE.** The universe-level commonalities are close interiority, a retrospective or reflective cast, a formal but readable register, material pre-industrial detail, animal and household imagery, plain speech tags, and chapter-opening frames. These are broad enough to survive a change of subseries, unlike the first-person memoir voice, which belongs to the Fitz books.

**INFERENCE.** The prose's characteristic movement is from sensory accumulation to reflective summary, then back to a short, flat sentence that lands the emotional cost. The long sentence is not decorative; it is the vehicle for a consciousness trying to hold several kinds of knowledge at once. The short sentence is not a modern minimalist gesture; it is the point where the accumulation becomes unbearable.

**INFERENCE.** Deliberate repetition works through motifs and phrases that return at moments of pressure. The translation should preserve the return when the source marks it, and avoid inventing refrains that the source does not support.

**EDITORIAL DECISION.** The universe base uses eight rules: narrative voice, register, sentence rhythm, dialogue, imagery, lexicon, punctuation, and formatting. It does not impose first person, because the third-person subseries must be able to inherit the base. It does not impose a named magic system or a named place. Those belong to the glossary and the book-level resources.

### 5.2 Farseer

**FACT.** The Farseer sample is the strongest evidence in the corpus for double time. The narrator reports what the child saw and, in the same breath, what the adult now understands. The prose can be syntactically complex even when the focalizer is a child, because the adult narrator's vocabulary is doing the remembering. The sample also contains direct address to the reader and explicit reflections on the reliability of memory.

**FACT.** *Royal Assassin* adds a further complication: in the sampled chapter, the first person enters the body and memory of another mind. The "I" can refer to the narrator or to the person whose senses he is borrowing. The Portuguese translation preserves the sequence. **INFERENCE.** Its habit of clarifying pronouns and unpacking elliptical clauses creates a risk of resolving the ambiguity.

**INFERENCE.** The Farseer profile needs to protect three things that the universe base states only generally: the memoir frame, the gap between child and adult knowledge, and the unstable referent of the first person in possession or dream sequences. It also needs to protect the shorter, more dialogue-driven rhythm of the second book without turning the whole trilogy into a clipped thriller.

**EDITORIAL DECISION.** The subseries override has six rules: narrative voice, register, sentence rhythm, formatting, dialogue, and lexicon. It replaces the base rules on those dimensions and leaves the base imagery and punctuation in place. The formatting rule is self-contained: it asks for white space between memoir frame and remembered scene, preserves chapter-opening documents, and protects the one-line emotional beat.

**INFERENCE.** The official Portuguese preserves the interiority, the sensory detail, and the chapter frames. It modernizes regional speech, unpacks some elliptical English clauses, and uses a mixed pronominal system with a European-leaning syntax. It also translates some place names and animal names while keeping character names. Those are translation-policy choices, not style rules; the glossary module should own them.

**HYPOTHESIS.** The Portuguese explicitation reduces the narrator's ironic gap. When an English ellipsis or unfinished clause is completed for clarity, the reader loses the sense that the adult narrator is still deciding how much to tell. This is testable by aligning passages where the English uses trailing ellipsis, interrupted speech, or a one-line paragraph. The current sample suggests the pattern but does not quantify it.

**EDITORIAL DECISION.** Do not fake archaism with *vós*, *outrossim*, or invented medievalisms. Use an elevated modern Portuguese, with formal address and slightly older connectives where the voice requires them. Do not calque English subject pronouns: Portuguese inflection carries the person, and an explicit *eu* should be reserved for emphasis or self-conscious narration. Do not copy the European Portuguese enclisis of the comparandum.

**EDITORIAL DECISION.** Preserve the Fool's riddling register and the stablemaster's clipped authority without naming them in the rule. The point is not to reproduce a fixed idiolect but to keep their speech recognizable as different from the narrator's. Do not complete their unfinished sentences for the reader.

### 5.3 Liveship Traders (provisional)

**FACT.** No local sample of this subseries was supplied. The profile is a structural prior, not a close reading.

**INFERENCE.** The known narrative situation is third-person limited with multiple viewpoints, a large mercantile family cast, maritime trade, and living ships. The main differences from the sampled Farseer books are the absence of a retrospective first-person memoir, the plural viewpoint structure, and the weight of nautical and commercial detail.

**EDITORIAL DECISION.** The provisional profile has seven rules: third-person limited voice, concrete commercial register, spatial sentence rhythm, viewpoint formatting, class-and-nation dialogue, maritime imagery, and precise nautical lexicon. It deliberately avoids claims about average sentence length, contraction density, or the exact ratio of dialogue to narration, because those cannot be observed locally.

**HYPOTHESIS.** The series will reward a translation that treats ships, cargo, credit, and family obligation as ordinary work rather than as fantasy spectacle. If the translation inflates the maritime material into epic description, it will lose the domestic-commercial texture that distinguishes this subseries from the Fitz books. Validate against three chapters before promoting the profile.

### 5.4 Tawny Man (provisional)

**FACT.** No local sample of this subseries was supplied.

**INFERENCE.** The known narrative situation is a return to first-person Fitz, now older, after the events of the Farseer trilogy. The voice is more measured and elegiac than the apprenticeship books, with a wider adult social world and a longer retrospective reach. The main risk is to restore the boy's unguarded voice or to recycle the earlier book's exact interiority.

**EDITORIAL DECISION.** The provisional profile has seven rules: aging first-person narrator, elegiac register, long reflective periods with short action cuts, adult intimacy as evasion, domestic and bodily imagery, lexical continuity, and understated reunion. It does not claim a measured difference in sentence length or dialogue ratio.

**HYPOTHESIS.** The series will read best if the narrator's age is carried by what he notices and what he refuses to explain, not by a slower sentence rate imposed from outside. Validate against three chapters.

### 5.5 Rain Wild Chronicles (provisional)

**FACT.** No local sample of this subseries was supplied.

**INFERENCE.** The known narrative situation is an ensemble of young third-person viewpoints on a river expedition, with physical hardship, dragons, and a faster pace than the Fitz books. The main differences are the plural young cast, the expedition structure, and the greater weight of dialogue and sensory immediacy.

**EDITORIAL DECISION.** The provisional profile has seven rules: young multiple viewpoint, concrete anti-memoir register, faster rhythm, scene-break formatting, adolescent dialogue, river-and-body imagery, and expedition lexicon. It deliberately does not import the Fitz memoir voice or the universe base's retrospective cast.

**HYPOTHESIS.** The translation should let the young characters be limited, embarrassed, and sometimes unlikeable. If every viewpoint is smoothed into the same articulate adult register, the ensemble will lose its social texture. Validate against three chapters.

### 5.6 Fitz and the Fool (provisional)

**FACT.** No local sample of this subseries was supplied.

**INFERENCE.** The known narrative situation is a late-series return to first-person Fitz, now older and darker, with a second younger focalizer and a strong weight of return, inheritance, and grief. The main risk is to treat the series as a victory lap for the earlier books, or to let the younger focalizer sound like a copy of the older narrator.

**EDITORIAL DECISION.** The provisional profile has six rules: late first-person frame, elegiac and sometimes brutal register, long retrospect with short flat cuts, family intimacy as shorthand, age-and-inheritance imagery, and lexical continuity. It does not claim a measured difference in sentence length or dialogue ratio.

**HYPOTHESIS.** The series will reward a translation that lets the past press on the present through what characters do not say. If every reunion is staged as an explanatory set piece, the late-series intimacy will become exposition. Validate against three chapters.

### 5.7 Hobb translation risks and decisions

**INFERENCE.** The first risk is flattening the double time. If the translation resolves every ambiguity about who knows what, the reader loses the memoir's characteristic tension between the boy's experience and the man's interpretation.

**INFERENCE.** The second risk is over-explaining the Fool. His speech is riddling, evasive, and sometimes prophetic. A translation that completes his sentences or adds explanatory tags will make him merely cryptic or merely cute.

**INFERENCE.** The third risk is fake archaism. The English has a light archaic flavor, not a fully reconstructed older English. Portuguese *vós*, obsolete connectives, or invented medievalisms would overstate the distance and make the prose unreadable.

**INFERENCE.** The fourth risk is pronoun calque. English repeats subject pronouns because English grammar requires them; Portuguese does not. A translation that begins every sentence with *eu* will sound translated even when the vocabulary is correct.

**EDITORIAL DECISION.** Use Brazilian Portuguese norms for pronoun placement and address. Keep the register elevated but modern. Preserve the chapter frames and the one-line beats. Let the glossary module settle names and invented terms. Validate the provisional subseries before promoting them.

## 6. Sun Eater

### 6.1 What the prose does

**FACT.** The two English samples are first-person retrospective narratives. The narrator writes after the events, knows more than the participants, and comments on memory, history, and his own legend. He addresses the reader directly. The prose moves between clipped scene work and long expository periods. The three-chapter sample means are 13.28 and 13.84 words; the p90 is 26 and 27; the short-fragment share is 14.9% in both books. The dialogue-paragraph ratios are 0.432 and 0.418. The full-book means are 13.25 and 13.64.

**FACT.** The two books use short paragraphs as a structural device: 26 paragraphs of five words or fewer in *Howling Dark*, 40 in *Demon in White*, and two one-word paragraphs in each sample. *Demon in White* also carries a larger share of court ritual, imperial history, and political argument, while *Howling Dark* opens with disorientation and a revival scene. The sample means are close, but the scene types are not.

**FACT.** The speech-tag set is *said*-dominant: 70.6% in *Howling Dark* and 60.0% in *Demon in White*. Dialogue is clipped, title-conscious, and often conducted as a verbal duel. Characters interrupt, refuse to answer, and use rank as a weapon.

**INFERENCE.** The narrator's voice is a deliberate amalgam of classical historian, military memoirist, and self-mythologizing survivor. The grandeur is real, but it is always undercut by irony, bodily weakness, or political farce. The prose is not solemn; it is theatrical and self-aware.

**INFERENCE.** The series' rhythm is scene-dependent rather than uniformly baroque. Court ritual and exposition invite long accumulative periods; disorientation, combat, and revelation invite fragments and one-line paragraphs. A translation that applies one rhythm to every scene will either flatten the action or inflate the introspection.

**INFERENCE.** The imagery is cosmic in scale but physical in detail: light and darkness, fire and glass, flesh and machinery, imperial architecture. The comparisons are precise enough to be seen, not merely asserted. The lexicon is techno-archaic and Latinate, with invented terms that the narrator uses without glossing.

**INFERENCE.** Deliberate repetition works through recurring motifs and titles rather than through repeated phrasing. The narrator returns to the same images when a memory returns, and the repetition signals obsession rather than a stylistic tic. The translation should preserve those returns when the source repeats them, and vary the wording when it does not.

### 6.2 What the published Portuguese appears to preserve and change

**FACT.** The Portuguese sample is from book one, not from the two sampled English books. It preserves the retrospective first person, the direct address to the reader, the high register, the fragments, the em dashes, and the invented terminology. It uses a mixed pronominal syntax with features associated with European Portuguese. Its mean sentence is 15.58 words, against 13.28 and 13.84 in the English samples; the comparison is cross-book and cannot establish a translation-level expansion.

**INFERENCE.** The Portuguese translation's main gain is readability at the level of the sentence: long English periods are often unpacked into clearer Portuguese clauses. The main risk is that the unpacking explains too much. The narrator's authority depends on his ability to hold a long thought in suspension; if every period is broken into shorter units, the prose can become a report of the thought rather than the thought itself.

**INFERENCE.** The Portuguese sample's explicit subject pronouns are more frequent than Brazilian prose usually needs. Some of that is rhetorical self-consciousness, but some reads as source interference. **EDITORIAL DECISION.** The translation should let verb inflection carry the person and reserve *eu* for emphasis.

**HYPOTHESIS.** An aligned comparison of book one would show that the Portuguese translation expands compressed English periods and clarifies ambiguous referents. The current cross-book comparison cannot distinguish a translation habit from a difference between books. This is the first measurement to run before revising the profile.

### 6.3 Translation risks

**INFERENCE.** The first risk is over-literal Latinate syntax. Portuguese can support long, subordinate sentences, but it cannot reproduce English participial shortcuts without sounding artificially bookish. The translation should preserve the architecture of the period, not its exact clause order.

**INFERENCE.** The second risk is flattening the aphorisms. The narrator's short declarative judgments depend on their placement and their lack of explanation. If the translation expands them into full paragraphs, or adds a connective that explains why they matter, the voice loses its authority.

**INFERENCE.** The third risk is losing the irony. The narrator is capable of genuine grandeur and genuine self-mockery in the same paragraph. A translation that plays the grandeur straight will make him pompous; one that plays the irony too broadly will make him flippant.

**INFERENCE.** The fourth risk is over-explaining the classical and religious allusions. The narrator assumes a reader who can catch them. A translation that glosses every reference will turn the novel into an annotated edition.

**EDITORIAL DECISION.** Keep the direct address to the reader. Keep the fragments and the one-line paragraphs. Keep the high register, but do not add new archaisms. Do not gloss invented terms inside the narrative. Do not copy the Portuguese sample's explicitation or its European-leaning pronoun syntax.

### 6.4 Profile rationale

The eight rules map to the observable tendencies:

- `narrative_voice` protects the retrospective historian and his self-mythology.
- `register` protects the elevated, ironic register.
- `sentence_rhythm` protects the scene-dependent extremes.
- `dialogue` protects the clipped, title-conscious verbal duel.
- `imagery` protects the cosmic-but-physical comparison.
- `lexicon` protects the techno-archaic vocabulary and the no-gloss rule.
- `punctuation` protects the em dash and the rhetorical semicolon.
- `formatting` protects the isolated one-line paragraph, the chapter titles, the epigraph-like openings, and the white space.

Paragraph isolation and document architecture are both handled by `formatting`, which is the upstream dimension for paragraph length and section breaks.

## 7. Cross-cutting decisions

### 7.1 Dialogue punctuation and paragraph splitting

**FACT.** The English editions use quotation marks; the Portuguese editions use the travessão. **INFERENCE.** The higher dialogue-paragraph ratio is consistent with the Portuguese editions giving more speech turns their own paragraph.

**EDITORIAL DECISION.** Treat this as a typographic convention, not a style difference. Do not increase the dialogue-paragraph ratio to match the Portuguese comparandum. Do not count the Portuguese dash rate as evidence of a more interrupted prose. Preserve the source's paragraph logic for interiority and reflection; use the target convention for speech.

### 7.2 Contractions and orality

**FACT.** English contractions run from 15 to 23 per 1,000 words in the sampled books. Portuguese has no direct equivalent, and the Portuguese samples contain none of the English-type contractions.

**EDITORIAL DECISION.** Do not invent contractions or reductions to match a number. Render orality through syntax, address, and lexical choice. *Lonesome Dove* can use standard Brazilian colloquialism with *você* and full *para*; *Realm of the Elderlings* should stay elevated and slightly formal; *Sun Eater* should stay formal and Latinate. The register rule in each profile carries this decision.

### 7.3 Pronouns and Portuguese variety

**FACT.** The Portuguese comparanda are mixed. **INFERENCE.** The Hobb samples show preposed possessives and enclisis at rates consistent with European Portuguese. The Lonesome Dove sample is closer to Brazilian colloquial usage. The Sun Eater sample is mixed.

**EDITORIAL DECISION.** Target Brazilian Portuguese. Do not copy European Portuguese enclisis, preposed possessives, or *a + infinitive* constructions from the comparanda. Do not calque English subject pronouns. Choose *você* or *tu* per character and region, and keep the choice consistent. Avoid the mixed pronominal system of the Hobb sample, which uses *você* as subject with *te* as object.

### 7.4 Archaism and invented terms

**EDITORIAL DECISION.** No pseudo-archaic Portuguese. Use elevated modern prose for Hobb and Sun Eater, and standard colloquial prose for Lonesome Dove. Let invented terms arrive through use; do not add explanatory glosses inside the narrative. The glossary module owns the actual term choices.

**FACT.** The samples show character names kept in English and some place names and animal names translated. This is not enough to infer a general policy. Do not create glossary entries from this brief; another module handles terminology.

### 7.5 Metrics and imitation

**INFERENCE.** The sample metrics are useful for detecting large tendencies, not for setting targets. A translation that tries to match a mean sentence length or a dialogue ratio will sound engineered. The profiles therefore describe distributions and scene-dependent behavior, not averages.

**EDITORIAL DECISION.** Use the full-book metrics as a sanity check after translation, not as a constraint during translation. If a chapter's mean sentence length drifts far from the book's baseline, inspect the cause; do not split or merge sentences to hit a number.

### 7.6 Names and terminology

**EDITORIAL DECISION.** This brief does not create glossary entries. The confirmed names and terms in the project context are inputs for the glossary module, not style rules. The rule instructions deliberately avoid naming characters, places, or invented terms so that they remain reusable across books and editions.

## 8. Profile inventory

| File | Scope | Rules | Dimensions | Basis | Confidence |
|---|---|---:|---|---|---|
| `literary-resources/larry-mcmurtry/lonesome-dove/style.yaml` | Book | 9 | voice, register, rhythm, formatting, dialogue, imagery, lexicon, punctuation, other | EN/PT samples and full-book metrics | Sampled |
| `literary-resources/robin-hobb/realm-of-the-elderlings/style.yaml` | Universe | 8 | voice, register, rhythm, dialogue, imagery, lexicon, punctuation, formatting | Farseer 1/2 EN/PT samples and full-book metrics | Sampled, Farseer-weighted |
| `literary-resources/robin-hobb/realm-of-the-elderlings/farseer/style.yaml` | Subseries | 6 | voice, register, rhythm, formatting, dialogue, lexicon | Farseer 1/2 EN/PT samples | Sampled |
| `literary-resources/robin-hobb/realm-of-the-elderlings/liveship-traders/style.yaml` | Subseries | 7 | voice, register, rhythm, formatting, dialogue, imagery, lexicon | Structural prior | Provisional |
| `literary-resources/robin-hobb/realm-of-the-elderlings/tawny-man/style.yaml` | Subseries | 7 | voice, register, rhythm, dialogue, imagery, lexicon, other | Structural prior | Provisional |
| `literary-resources/robin-hobb/realm-of-the-elderlings/rain-wild-chronicles/style.yaml` | Subseries | 7 | voice, register, rhythm, formatting, dialogue, imagery, lexicon | Structural prior | Provisional |
| `literary-resources/robin-hobb/realm-of-the-elderlings/fitz-and-the-fool/style.yaml` | Subseries | 6 | voice, register, rhythm, dialogue, imagery, lexicon | Structural prior | Provisional |
| `literary-resources/christopher-ruocchio/sun-eater/style.yaml` | Series | 8 | voice, register, rhythm, dialogue, imagery, lexicon, punctuation, formatting | EN books 2/3 and PT book 1 samples; full-book metrics | Sampled, cross-book PT comparison |

The compiled Farseer profile has eight rules because the six overrides replace six base dimensions and the base imagery and punctuation rules remain. The provisional profiles compile against the universe base in the same way; their rule counts are the number of overrides, not the final compiled count.

## 9. Open questions and next checks

1. **Aligned sentence comparison.** Align the English and Portuguese *Lonesome Dove* and Farseer samples at sentence level to measure splitting, merging, and explicitation. The current metrics cannot distinguish translation policy from chapter-level variation.
2. **Sun Eater book one.** Obtain an English sample of book one to compare with the Portuguese sample. Until then, the Sun Eater PT observations are cross-book.
3. **Provisional subseries.** Before promoting Liveship Traders, Tawny Man, Rain Wild Chronicles, or Fitz and the Fool, read at least three chapters of each in English and, if available, the published Portuguese. Revise the rules against observed sentence rhythm, dialogue ratio, and viewpoint handling.
4. **Portuguese variety.** Confirm the publication variety of each comparandum. The current samples are mixed, and the Hobb and Sun Eater samples show European-leaning features. Do not let a comparandum with European Portuguese features set the target norm.
5. **Terminology audit.** The glossary module should settle names, invented terms, titles, and institutional vocabulary. This brief deliberately does not.
6. **Full-book style extraction.** Run the repository's extractor on the full books and compare its rules with these hand-authored profiles. The extractor may surface tendencies that three chapters cannot show, especially in the later Farseer and Sun Eater books.

## 10. Artifact list

- `literary-resources/larry-mcmurtry/lonesome-dove/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/farseer/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/liveship-traders/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/tawny-man/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/rain-wild-chronicles/style.yaml`
- `literary-resources/robin-hobb/realm-of-the-elderlings/fitz-and-the-fool/style.yaml`
- `literary-resources/christopher-ruocchio/sun-eater/style.yaml`
- `docs/project/EDITORIAL_PROFILES.md`
