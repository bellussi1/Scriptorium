# Resource pass: Realm of the Elderlings and Sun Eater

Date: 2026-11-09

## Decisions applied

- Terms without an official PT-BR edition are provisional (`confidence: provisional`, `approved: false`) and can be revised after review.
- Ship of Magic and Howling Dark are the approved terminology canon for their series; their Portuguese surface forms win over editorial guesses.
- Malazan is split now; glossary and style are deferred until after the Realm and Sun Eater passes.

## Realm of the Elderlings

Added or expanded:

- `robin-hobb/realm-of-the-elderlings/glossary.yaml`: Buckkeep → Torre do Cervo, Buck, Farrow, Skill → Talento, Wit → Manha, Elderlings → Antigos, Others → Outros, and the official `ilhéu` demonym.
- `liveship-traders/characters.yaml`: Keffria, Kyle, Selden, Reyn, Jani, Davad, Etta, Sorcor, Grag, Cosgo, Amber, Jek, Serilla, Rache, Clef, Ephron, Torg, Cerwin, Gankis, Mingsley, Ophelia, Maulkin, Shreever, Sessurea, Tintaglia, She Who Remembers, Bolt.
- `liveship-traders/glossary.yaml`: navio vivo, Trader, Old/New Traders, Bingtown, Jamaillia, Chalced, Divvytown, Rain Wild, Pirate Isles, Satrap and related forms.
- `tawny-man/characters.yaml`: Thick, Lord Golden, Tom Badgerlock, Web, Peottre, Elliania, Narcheska, Starling, Hap, Nighteyes, Jinna, Laudwine, Civil Bresinga, Myblack, Icefyre, Pale Woman, Black Man.
- `tawny-man/glossary.yaml`: Old Blood → Sangue Antigo, Piebalds → Malhados, Catalyst → Catalisador, White Prophet → Profeta Branco, Hetgurd, Aslevjal, Outislander → ilhéu.
- `liveship-traders/style.yaml` and `tawny-man/style.yaml`: rewritten with measurements from the first three content documents of each book and new rules for liveship/serpent consciousness and the Manha/Talento distinction.

Compiled term counts:

| Book | Terms |
|---|---:|
| The Mad Ship | 77 |
| Ship of Destiny | 78 |
| Fool's Errand | 60 |
| Ship of Magic | 73 |

## Sun Eater

Expanded `characters.yaml`, `glossary.yaml` and `worldbuilding.yaml` with the post-Howling Dark cast and setting: Lorian, Selene, Edouard, Alexander, Syriani Dorayaica, Gibson, Kharn Sagara, Olorin, William XXIII, Otavia Corvo, Nicephorus, Siran, Cassandra; Tamerlane, Demiurge, Ascalon; Forum, Gododdin, Jadd, Dharan-Tun, Pale, Eue, Akterumu, Colchis, Judecca, Patmos; Imperium, Watchers, Irchtani, Quiet; Lord Marlowe.

Compiled term counts:

| Book | Terms |
|---|---:|
| Demon in White | 64 |
| Kingdoms of Death | 67 |
| Ashes of Man | 70 |
| Disquiet Gods | 75 |
| Shadows Upon Time | 75 |

## Validation

- `python -m src.literary.cli resources validate --root literary-resources`: **passed**, 25 files, no issues.
- Compiled glossary for The Mad Ship and Demon in White with no issues.
- Sample translation: 5 excerpts per book with Hy-MT2 7B Q4_K_M, the compiled glossary and style.
  - Name recall 1.0; English leakage 0.0; no generation errors.
  - The outputs kept `Satrap`, `Traders`, `Jamaillia City`, `chalcedeanos`, `cielcin`, `Legiões` and the Manha/Talento distinction.
  - Latency in this round was not comparable to the earlier 5.5 s/excerpt baseline because the GPU was shared with desktop processes (50–189 s/excerpt). The quality sample passes; speed needs an idle-GPU rerun.

## Malazan split

The Calibre omnibus 343 was split into ten EPUBs under `data/calibre/malazan-split/`:

- 10 files, 37–50 documents each.
- All ten pass EPUBCheck 5.4.0 with **0 fatals / 0 errors / 0 warnings**.
- The split is recorded in `literary-resources/steven-erikson/malazan-book-of-the-fallen/series.yaml`.
- The split outputs are not imported into Calibre; that is a separate, explicit step.

## Next

1. Review the provisional terms with the user.
2. Run the idle-GPU speed sample before the full The Mad Ship / Demon in White run.
3. Add the Malazan glossary and style after the Realm and Sun Eater passes.
