"""Tests for the literary benchmark adapters.

These tests pin the official GGUF tags, the model-specific prompt templates and
the sampling options. They are intentionally offline: no model is called.
"""
from __future__ import annotations

import json

import pytest

from benchmark.literary import adapters
from benchmark.literary.runner import load_glossary_file, load_style_file


def test_specialized_model_tags_are_real() -> None:
    assert adapters.MODELS["hy-mt2-7b"].model == "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
    assert (
        adapters.MODELS["index-translate-9b"].model
        == "hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M"
    )


def test_specialized_models_fit_the_8gb_profile() -> None:
    hy = adapters.MODELS["hy-mt2-7b"]
    index = adapters.MODELS["index-translate-9b"]
    assert hy.context_window == 8192
    assert index.context_window == 8192
    assert hy.temperature == 0.7
    assert hy.top_p == 0.6
    assert hy.top_k == 20
    assert hy.repeat_penalty == 1.05
    assert index.think is False
    assert index.temperature == 0.0


def test_hy_mt2_glossary_prompt_uses_its_terminology_template() -> None:
    messages = adapters.build_prompt(
        adapters.MODELS["hy-mt2-7b"],
        "The Fugue was quiet.",
        glossary={"Fugue": "Fuga"},
        style="Keep the narrative voice.",
    )
    content = messages[0]["content"]
    assert "[Source Text]" in content
    assert "[Translation Tasks]" in content
    assert "Terminology (mandatory): Fugue -> Fuga" in content
    assert "Style: Keep the narrative voice." in content
    assert "Brazilian Portuguese" in content
    assert "The Fugue was quiet." in content


def test_index_glossary_prompt_uses_insttrans_constraints() -> None:
    messages = adapters.build_prompt(
        adapters.MODELS["index-translate-9b"],
        "The Fugue was quiet.",
        glossary={"Fugue": "Fuga"},
        style="Keep the narrative voice.",
    )
    content = messages[0]["content"]
    assert "[Source]" in content
    assert "[Constraints]" in content
    assert "[Hard Constraint] Terminology mapping: Fugue -> Fuga" in content
    assert "[Note] Style: Keep the narrative voice." in content
    assert "Brazilian Portuguese" in content
    assert "The Fugue was quiet." in content


def test_default_prompts_do_not_add_empty_constraints() -> None:
    hy = adapters.build_prompt(adapters.MODELS["hy-mt2-7b"], "Hello.")
    index = adapters.build_prompt(adapters.MODELS["index-translate-9b"], "Hello.")
    assert "Terminology" not in hy[0]["content"]
    assert "Constraints" not in index[0]["content"]
    assert "Hello." in hy[0]["content"]
    assert "Hello." in index[0]["content"]


def test_ollama_payload_uses_model_specific_sampling(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "message": {"content": "ok"},
                "prompt_eval_count": 3,
                "eval_count": 2,
            }

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(adapters.requests, "post", fake_post)

    generation = adapters.generate_ollama(
        adapters.MODELS["hy-mt2-7b"],
        [{"role": "user", "content": "Hello."}],
    )

    assert generation.text == "ok"
    options = captured["json"]["options"]
    assert options["temperature"] == 0.7
    assert options["top_p"] == 0.6
    assert options["top_k"] == 20
    assert options["repeat_penalty"] == 1.05
    assert options["num_ctx"] == 8192
    assert captured["json"]["model"] == "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"


def test_index_payload_disables_thinking(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": "ok"}}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(adapters.requests, "post", fake_post)

    adapters.generate_ollama(
        adapters.MODELS["index-translate-9b"],
        [{"role": "user", "content": "Hello."}],
    )

    assert captured["json"]["think"] is False


def test_quantization_specs_are_present() -> None:
    assert adapters.MODELS["hy-mt2-7b-q6"].model.endswith(":Q6_K")
    assert adapters.MODELS["hy-mt2-7b-q8"].model.endswith(":Q8_0")
    assert adapters.MODELS["hy-mt2-7b-q6"].temperature == 0.7


def test_compiled_glossary_and_style_files_are_accepted(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        json.dumps(
            {
                "terms": [
                    {"source": "Fugue", "target": "Fuga", "forbidden": ["F?ria"]},
                    {"source": "Sun Eater|Sun-Eater", "target": "Devorador do Sol"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    glossary = load_glossary_file(str(glossary_path))
    assert glossary["Fugue"] == "Fuga"
    assert glossary["Sun Eater"] == "Devorador do Sol"
    assert glossary["Sun-Eater"] == "Devorador do Sol"

    style_path = tmp_path / "style.yaml"
    style_path.write_text(
        "translation: Keep the retrospective first person.\nrefinement: Preserve the voice.\n",
        encoding="utf-8",
    )
    assert "retrospective" in load_style_file(str(style_path))
