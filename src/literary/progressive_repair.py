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
    "abafar": "abafando",
    "abater": "abatendo",
    "abordar": "abordando",
    "acabar": "acabando",
    "acalmar": "acalmando",
    "aclimatizar": "aclimatizando",
    "acontecer": "acontecendo",
    "acordar": "acordando",
    "afastar": "afastando",
    "afugentar": "afugentando",
    "aguentar": "aguentando",
    "ajudar": "ajudando",
    "alvejar": "alvejando",
    "andar": "andando",
    "angular": "angulando",
    "apertar": "apertando",
    "aprender": "aprendendo",
    "argumentar": "argumentando",
    "assaltar": "assaltando",
    "assumir": "assumindo",
    "avançar": "avançando",
    "bater": "batendo",
    "brincar": "brincando",
    "buscar": "buscando",
    "cair": "caindo",
    "caminhar": "caminhando",
    "carregar": "carregando",
    "cavar": "cavando",
    "caçar": "caçando",
    "chamar": "chamando",
    "chegar": "chegando",
    "chorar": "chorando",
    "citar": "citando",
    "comandar": "comandando",
    "começar": "começando",
    "cometer": "cometendo",
    "comunicar": "comunicando",
    "confundir": "confundindo",
    "construir": "construindo",
    "contemplar": "contemplando",
    "continuar": "continuando",
    "convulsionar": "convulsionando",
    "correr": "correndo",
    "crescer": "crescendo",
    "criar": "criando",
    "dançar": "dançando",
    "dar": "dando",
    "decidir": "decidindo",
    "declinar": "declinando",
    "decorrer": "decorrendo",
    "deixar": "deixando",
    "demorar": "demorando",
    "desaparecer": "desaparecendo",
    "descer": "descendo",
    "desenvolver": "desenvolvendo",
    "desfrutar": "desfrutando",
    "desperdiçar": "desperdiçando",
    "destruir": "destruindo",
    "detetar": "detectando",
    "dirigir": "dirigindo",
    "dizer": "dizendo",
    "dormir": "dormindo",
    "duplicar": "duplicando",
    "encarar": "encarando",
    "enfrentar": "enfrentando",
    "entrar": "entrando",
    "entregar": "entregando",
    "enviar": "enviando",
    "escanear": "escaneando",
    "esconder": "escondendo",
    "escrever": "escrevendo",
    "escutar": "escutando",
    "esvaecer": "esvanecendo",
    "exagerar": "exagerando",
    "falar": "falando",
    "fazer": "fazendo",
    "ferver": "fervendo",
    "ficar": "ficando",
    "fritar": "fritando",
    "fugir": "fugindo",
    "funcionar": "funcionando",
    "gritar": "gritando",
    "ignorar": "ignorando",
    "imaginar": "imaginando",
    "impor": "impondo",
    "incendiar": "incendiando",
    "incinerar": "incinerando",
    "incomodar": "incomodando",
    "iniciar": "iniciando",
    "interpretar": "interpretando",
    "invadir": "invadindo",
    "investigar": "investigando",
    "ir": "indo",
    "jogar": "jogando",
    "lançar": "lançando",
    "ler": "lendo",
    "levar": "levando",
    "lidar": "lidando",
    "liderar": "liderando",
    "lutar": "lutando",
    "manter": "mantendo",
    "mentir": "mentindo",
    "minerar": "minerando",
    "morrer": "morrendo",
    "mostrar": "mostrando",
    "mudar": "mudando",
    "navegar": "navegando",
    "observar": "observando",
    "ocorrer": "ocorrendo",
    "oferecer": "oferecendo",
    "olhar": "olhando",
    "orientar": "orientando",
    "ouvir": "ouvindo",
    "partir": "partindo",
    "passar": "passando",
    "pastar": "pastando",
    "pedir": "pedindo",
    "pensar": "pensando",
    "perceber": "percebendo",
    "percorrer": "percorrendo",
    "perder": "perdendo",
    "perguntar": "perguntando",
    "perseguir": "perseguindo",
    "piorar": "piorando",
    "planear": "planejando",
    "ponderar": "ponderando",
    "preparar": "preparando",
    "procurar": "procurando",
    "prosseguir": "prosseguindo",
    "quebrar": "quebrando",
    "querer": "querendo",
    "rastrear": "rastreando",
    "receber": "recebendo",
    "reconstruir": "reconstruindo",
    "recordar": "recordando",
    "recuar": "recuando",
    "registar": "registrando",
    "regressar": "regressando",
    "representar": "representando",
    "respirar": "respirando",
    "responder": "respondendo",
    "retirar": "retirando",
    "rever": "revendo",
    "sair": "saindo",
    "salvar": "salvando",
    "sangrar": "sangrando",
    "ser": "sendo",
    "sitiar": "sitiando",
    "sofrer": "sofrendo",
    "sorrir": "sorrindo",
    "subir": "subindo",
    "tecer": "tecendo",
    "tentar": "tentando",
    "ter": "tendo",
    "testar": "testando",
    "tocar": "tocando",
    "trabalhar": "trabalhando",
    "trair": "traindo",
    "tratar": "tratando",
    "travar": "travando",
    "trazer": "trazendo",
    "treinar": "treinando",
    "tremer": "tremendo",
    "usar": "usando",
    "vaguear": "vagueando",
    "vasculhar": "vasculhando",
    "vender": "vendendo",
    "ver": "vendo",
    "vestir": "vestindo",
    "viajar": "viajando",
    "vir": "vindo",
    "visar": "visando",
    "viver": "vivendo",
    "voltar": "voltando",
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
