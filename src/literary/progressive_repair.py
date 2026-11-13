"""Rewrite the pt-PT progressive periphrasis ("estou a falar") as pt-BR ("estou falando").

Only the verbs listed in ``PROGRESSIVE_GERUNDS`` are rewritten. The list is explicit on purpose:
after "a", a word that ends in -r is often a noun ("a dor", "a favor de"), so a suffix rule is
not safe. Every other "estar + a + word" is reported in ``unconverted`` for review, not changed.

Text is rewritten only outside tags, so attributes and markup are never touched.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from typing import Dict, List, Tuple

# pt-PT infinitive -> pt-BR gerund. pt-PT spellings in the infinitive (detetar, planear,
# escanear, esvaecer, aclimatizar) are mapped to the gerund pt-BR readers expect.
PROGRESSIVE_GERUNDS: Dict[str, str] = {
    "abater": "abatendo",
    "aclimatizar": "aclimatizando",
    "acontecer": "acontecendo",
    "afastar": "afastando",
    "aguentar": "aguentando",
    "alvejar": "alvejando",
    "andar": "andando",
    "aprender": "aprendendo",
    "bater": "batendo",
    "brincar": "brincando",
    "buscar": "buscando",
    "cair": "caindo",
    "caminhar": "caminhando",
    "carregar": "carregando",
    "chamar": "chamando",
    "chegar": "chegando",
    "comandar": "comandando",
    "comunicar": "comunicando",
    "construir": "construindo",
    "criar": "criando",
    "decidir": "decidindo",
    "decorrer": "decorrendo",
    "deixar": "deixando",
    "desaparecer": "desaparecendo",
    "descer": "descendo",
    "detetar": "detectando",
    "dirigir": "dirigindo",
    "dizer": "dizendo",
    "duplicar": "duplicando",
    "entrar": "entrando",
    "entregar": "entregando",
    "enviar": "enviando",
    "escanear": "escaneando",
    "escutar": "escutando",
    "esvaecer": "esvanecendo",
    "exagerar": "exagerando",
    "falar": "falando",
    "fazer": "fazendo",
    "funcionar": "funcionando",
    "gritar": "gritando",
    "imaginar": "imaginando",
    "impor": "impondo",
    "interpretar": "interpretando",
    "invadir": "invadindo",
    "investigar": "investigando",
    "ir": "indo",
    "jogar": "jogando",
    "ler": "lendo",
    "lidar": "lidando",
    "liderar": "liderando",
    "lutar": "lutando",
    "mentir": "mentindo",
    "minerar": "minerando",
    "morrer": "morrendo",
    "mostrar": "mostrando",
    "mudar": "mudando",
    "navegar": "navegando",
    "observar": "observando",
    "ocorrer": "ocorrendo",
    "olhar": "olhando",
    "ouvir": "ouvindo",
    "passar": "passando",
    "pensar": "pensando",
    "perceber": "percebendo",
    "percorrer": "percorrendo",
    "perder": "perdendo",
    "perguntar": "perguntando",
    "piorar": "piorando",
    "planear": "planejando",
    "ponderar": "ponderando",
    "procurar": "procurando",
    "querer": "querendo",
    "rastrear": "rastreando",
    "recordar": "recordando",
    "representar": "representando",
    "respirar": "respirando",
    "retirar": "retirando",
    "rever": "revendo",
    "salvar": "salvando",
    "ser": "sendo",
    "sitiar": "sitiando",
    "sorrir": "sorrindo",
    "tecer": "tecendo",
    "tentar": "tentando",
    "ter": "tendo",
    "testar": "testando",
    "trabalhar": "trabalhando",
    "tratar": "tratando",
    "travar": "travando",
    "trazer": "trazendo",
    "tremer": "tremendo",
    "vasculhar": "vasculhando",
    "ver": "vendo",
    "viajar": "viajando",
    "visar": "visando",
    "viver": "vivendo",
}

# Finite forms of "estar" that can start the periphrasis.
ESTAR_FORMS = (
    "estou|estás|está|estamos|estais|estão|estava|estavas|estávamos|estáveis|estavam|"
    "estive|estiveste|esteve|estivemos|estivestes|estiveram|estarei|estarás|estará|"
    "estaremos|estareis|estarão|estaria|estarias|estaríamos|estaríeis|estariam|"
    "esteja|estejas|estejamos|estejam|estivesse|estivessem|estiver|estiverem|estando|estar"
)

_VERBS = "|".join(re.escape(verb) for verb in sorted(PROGRESSIVE_GERUNDS, key=len, reverse=True))
_PERIPHRASIS_RE = re.compile(
    rf"(?<![\w-])({ESTAR_FORMS})(\s+)a\s+({_VERBS})(?![\w-])",
    re.IGNORECASE,
)
# Any "estar + a + word" whose word looks like an infinitive. Used only to report leftovers.
_LEFTOVER_RE = re.compile(
    rf"(?<![\w-])(?:{ESTAR_FORMS})\s+a\s+([^\W\d_]+(?:ar|er|ir|or|ôr|por))(?![\w-])",
    re.IGNORECASE,
)
_TAG_SPLIT_RE = re.compile(r"(<[^>]*>)")
TEXT_ENTRY_SUFFIXES = (".xhtml", ".html", ".htm")


def _swap(match: re.Match) -> str:
    estar, space, verb = match.group(1), match.group(2), match.group(3)
    gerund = PROGRESSIVE_GERUNDS[verb.lower()]
    if verb[:1].isupper():
        gerund = gerund[:1].upper() + gerund[1:]
    return f"{estar}{space}{gerund}"


def repair_progressive_html(html: str) -> Tuple[str, Counter, Counter]:
    """Return the rewritten markup, a count per verb rewritten, and leftovers to review."""
    converted: Counter = Counter()
    leftovers: Counter = Counter()

    def count(match: re.Match) -> str:
        converted[match.group(3).lower()] += 1
        return _swap(match)

    parts = _TAG_SPLIT_RE.split(html)
    for index in range(0, len(parts), 2):  # even indexes are text, odd indexes are tags
        text = parts[index]
        text = _PERIPHRASIS_RE.sub(count, text)
        for match in _LEFTOVER_RE.finditer(text):
            word = match.group(1).lower()
            if word not in PROGRESSIVE_GERUNDS:
                leftovers[word] += 1
        parts[index] = text
    return "".join(parts), converted, leftovers


def repair_progressive_in_epub(source_path: str, output_path: str) -> Dict[str, object]:
    """Copy an EPUB, rewriting pt-PT progressive periphrasis in its XHTML text.

    Nothing else changes: entries are copied in their original order with their original
    metadata, and only text outside tags is edited.
    """
    with zipfile.ZipFile(source_path, "r") as source:
        items = source.infolist()
        contents = {item.filename: source.read(item.filename) for item in items}

    converted_total: Counter = Counter()
    leftovers_total: Counter = Counter()
    changed_files: List[Dict[str, object]] = []
    outputs: Dict[str, bytes] = {}
    for item in items:
        name = item.filename
        if not name.lower().endswith(TEXT_ENTRY_SUFFIXES):
            continue
        original = contents[name].decode("utf-8", "replace")
        rewritten, converted, leftovers = repair_progressive_html(original)
        converted_total.update(converted)
        leftovers_total.update(leftovers)
        if rewritten != original:
            outputs[name] = rewritten.encode("utf-8")
            changed_files.append({"file": name, "changes": sum(converted.values())})

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as target:
        for item in items:
            target.writestr(item, outputs.get(item.filename, contents[item.filename]))
    return {
        "source": source_path,
        "out": output_path,
        "total_changes": sum(converted_total.values()),
        "by_verb": dict(converted_total.most_common()),
        "changed_files": changed_files,
        "unconverted": dict(leftovers_total.most_common()),
    }
