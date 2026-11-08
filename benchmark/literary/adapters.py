"""Model-specific prompt adapters for the literary benchmark.

The point is to avoid a rigged comparison: each model gets the prompt it was
trained to expect in the native round, plus a controlled literary round where
the instruction layer is comparable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests


@dataclass
class ModelSpec:
    key: str
    label: str
    provider: str  # ollama | openai-compatible
    model: str
    prompt_style: str  # translategemma | hy_mt2 | index_translate | generic_literary
    context_window: int
    supports_glossary: bool = False
    native_prompt: bool = True
    think: Optional[bool] = None
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    repeat_penalty: float = 1.0
    notes: str = ""


MODELS: Dict[str, ModelSpec] = {
    "translategemma-12b": ModelSpec(
        key="translategemma-12b",
        label="TranslateGemma 12B (Q4_K_M)",
        provider="ollama",
        model="translategemma:12b",
        prompt_style="translategemma",
        context_window=4096,
        supports_glossary=False,
        notes="~2K-token training regime; fixed prompt; not designed for long glossary-heavy chapters.",
    ),
    "qwen3.5-4b": ModelSpec(
        key="qwen3.5-4b",
        label="Qwen3.5 4B",
        provider="ollama",
        model="qwen3.5:4b",
        prompt_style="generic_literary",
        context_window=8192,
        supports_glossary=True,
        think=False,
        notes="Fast smoke-test baseline; limited instruction adherence.",
    ),
    "qwen3-8b": ModelSpec(
        key="qwen3-8b",
        label="Qwen3 8B (Q4_K_M)",
        provider="ollama",
        model="qwen3:8b-q4_K_M",
        prompt_style="generic_literary",
        context_window=8192,
        supports_glossary=True,
        think=False,
    ),
    "qwen3-14b": ModelSpec(
        key="qwen3-14b",
        label="Qwen3 14B (Q4_K_M)",
        provider="ollama",
        model="qwen3:14b",
        prompt_style="generic_literary",
        context_window=8192,
        supports_glossary=True,
        think=False,
        notes="9.3 GB; will offload on 8 GB VRAM.",
    ),
    "hy-mt2-7b": ModelSpec(
        key="hy-mt2-7b",
        label="Tencent Hy-MT2 7B (Q4_K_M)",
        provider="ollama",
        model="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
        prompt_style="hy_mt2",
        context_window=8192,
        supports_glossary=True,
        temperature=0.7,
        top_p=0.6,
        top_k=20,
        repeat_penalty=1.05,
        notes="Apache-2.0; 33 languages; recommended sampling is temperature 0.7, top_p 0.6, top_k 20, repetition_penalty 1.05.",
    ),
    "hy-mt2-7b-q6": ModelSpec(
        key="hy-mt2-7b-q6",
        label="Tencent Hy-MT2 7B (Q6_K)",
        provider="ollama",
        model="hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K",
        prompt_style="hy_mt2",
        context_window=8192,
        supports_glossary=True,
        temperature=0.7,
        top_p=0.6,
        top_k=20,
        repeat_penalty=1.05,
        notes="Higher-quality official GGUF; larger weights may reduce context headroom or force offload on an 8 GB card.",
    ),
    "hy-mt2-7b-q8": ModelSpec(
        key="hy-mt2-7b-q8",
        label="Tencent Hy-MT2 7B (Q8_0)",
        provider="ollama",
        model="hf.co/tencent/Hy-MT2-7B-GGUF:Q8_0",
        prompt_style="hy_mt2",
        context_window=4096,
        supports_glossary=True,
        temperature=0.7,
        top_p=0.6,
        top_k=20,
        repeat_penalty=1.05,
        notes="Near-lossless official GGUF; likely exceeds 8 GB VRAM at 8K. Use 4K or accept offload and measure.",
    ),
    "index-translate-9b": ModelSpec(
        key="index-translate-9b",
        label="Index-Translate 9B (Q4_K_M)",
        provider="ollama",
        model="hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M",
        prompt_style="index_translate",
        context_window=8192,
        supports_glossary=True,
        think=False,
        notes="Apache-2.0; 150 languages; greedy decoding, instTrans constraints, thinking disabled; 8K context fits the 8 GB card without the 16K CPU offload.",
    ),
    "deepseek-flash": ModelSpec(
        key="deepseek-flash",
        label="DeepSeek V4.1 Flash",
        provider="openai-compatible",
        model="deepseek-flash",
        prompt_style="generic_literary",
        context_window=1_000_000,
        supports_glossary=True,
        native_prompt=False,
        notes="Cloud; requires explicit approval and an API key.",
    ),
    "gemini-3.8-flash": ModelSpec(
        key="gemini-3.8-flash",
        label="Gemini 3.8 Flash",
        provider="openai-compatible",
        model="gemini-3.8-flash",
        prompt_style="generic_literary",
        context_window=1_048_576,
        supports_glossary=True,
        native_prompt=False,
        notes="Cloud; uses an OpenAI-compatible gateway if configured.",
    ),
}


LITERARY_SYSTEM = """You are a professional literary translator working from English into Brazilian Portuguese. Your task is to translate the passage so that it reads as a work of literature written in Portuguese, not as a literal gloss.

Priorities:
1. Preserve meaning, including ambiguity, implication and deliberate repetition.
2. Preserve the narrator's voice, register and distance.
3. Write natural Brazilian Portuguese syntax and rhythm; do not mirror English word order.
4. Keep names, invented terms and forms of address exactly as the glossary dictates.
5. Do not add explanations, notes or commentary. Output only the translation.
"""


def _glossary_section(glossary: Optional[Dict[str, str]]) -> str:
    if not glossary:
        return ""
    lines = ["Terminology (mandatory):"]
    for source, target in glossary.items():
        lines.append(f"- {source} -> {target}")
    return "\n".join(lines) + "\n\n"


def _term_pairs(glossary: Optional[Dict[str, str]]) -> str:
    if not glossary:
        return ""
    return "; ".join(f"{source} -> {target}" for source, target in glossary.items())


def _style_section(style: Optional[str]) -> str:
    if not style:
        return ""
    return f"Style instructions:\n{style.strip()}\n\n"


def build_prompt(
    spec: ModelSpec,
    text: str,
    *,
    glossary: Optional[Dict[str, str]] = None,
    style: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Return chat messages for the model."""
    if spec.prompt_style == "translategemma":
        # Official prompt: one user message, two blank lines before the text.
        content = (
            "You are a professional English (en) to Portuguese (pt-BR) translator. "
            "Your goal is to accurately convey the meaning and nuances of the original English text "
            "while adhering to Portuguese grammar, vocabulary, and cultural sensitivities.\n"
            "Produce only the Portuguese translation, without any additional explanations or commentary. "
            "Please translate the following English text into Portuguese:\n\n\n"
            f"{text}"
        )
        return [{"role": "user", "content": content}]

    if spec.prompt_style == "hy_mt2":
        if glossary or style:
            tasks = []
            if glossary:
                tasks.append("Terminology (mandatory): " + _term_pairs(glossary))
            if style:
                tasks.append("Style: " + style.strip())
            tasks.append(
                "Translate the [Source Text] into Brazilian Portuguese. "
                "Output only the translation without any additional explanation."
            )
            content = (
                "[Source Text]\n"
                + text
                + "\n\n[Translation Tasks]\n"
                + "\n".join(f"{index}. {task}" for index, task in enumerate(tasks, 1))
            )
        else:
            content = (
                "Translate the following text into Brazilian Portuguese. Note that you should "
                "only output the translated result without any additional explanation:\n\n"
                + text
            )
        return [{"role": "user", "content": content}]

    if spec.prompt_style == "index_translate":
        if glossary or style:
            constraints = []
            if glossary:
                constraints.append(
                    "[Hard Constraint] Terminology mapping: " + _term_pairs(glossary)
                )
            if style:
                constraints.append("[Note] Style: " + style.strip())
            constraints.append("Output only the translation without any explanation.")
            content = (
                "Please translate the following text into Brazilian Portuguese and strictly "
                "follow all constraints.\n\n[Source]\n"
                + text
                + "\n\n[Constraints]\n"
                + "\n".join(f"{index}. {item}" for index, item in enumerate(constraints, 1))
            )
        else:
            content = (
                "Please translate the following text into Brazilian Portuguese. "
                "Output the translation directly, without any explanation:\n\n"
                + text
            )
        return [{"role": "user", "content": content}]

    system = LITERARY_SYSTEM
    if style:
        system += "\n" + style.strip()
    if glossary:
        system += "\n\n" + _glossary_section(glossary)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


@dataclass
class Generation:
    model: str
    text: str = ""
    latency_s: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "text": self.text,
            "latency_s": round(self.latency_s, 3),
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
            "raw_usage": self.raw,
        }


def generate_ollama(
    spec: ModelSpec,
    messages: List[Dict[str, str]],
    *,
    endpoint: str = "http://localhost:11434",
    temperature: Optional[float] = None,
    max_tokens: int = 1200,
    timeout: int = 900,
) -> Generation:
    started = time.time()
    payload = {
        "model": spec.model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": spec.temperature if temperature is None else temperature,
            "top_p": spec.top_p,
            "top_k": spec.top_k,
            "repeat_penalty": spec.repeat_penalty,
            "num_ctx": spec.context_window,
            "num_predict": max_tokens,
        },
    }
    if spec.think is not None:
        payload["think"] = spec.think
    try:
        response = requests.post(
            endpoint.rstrip("/") + "/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message") or {}
        return Generation(
            model=spec.key,
            text=(message.get("content") or "").strip(),
            latency_s=time.time() - started,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            raw={"done_reason": data.get("done_reason"), "total_duration": data.get("total_duration")},
        )
    except Exception as exc:
        return Generation(model=spec.key, latency_s=time.time() - started, error=str(exc))


def generate_openai_compatible(
    spec: ModelSpec,
    messages: List[Dict[str, str]],
    *,
    endpoint: str,
    api_key: str,
    temperature: float = 0.0,
    max_tokens: int = 1200,
    timeout: int = 900,
) -> Generation:
    started = time.time()
    try:
        response = requests.post(
            endpoint.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": spec.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return Generation(
            model=spec.key,
            text=(choice.get("message", {}).get("content") or "").strip(),
            latency_s=time.time() - started,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            raw={"finish_reason": choice.get("finish_reason")},
        )
    except Exception as exc:
        return Generation(model=spec.key, latency_s=time.time() - started, error=str(exc))
