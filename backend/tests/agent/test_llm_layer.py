"""IA-1: imágenes en el historial y modelo por proveedor y propósito."""

import base64

import pytest

from app.agent.loop import MODEL, OPENAI_MODEL, AnthropicLLM, image_block, model_for
from app.agent.openai_llm import OpenAILLM, response_input

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
ENV_VARS = [f"BRANCHPOINT_{p}_{u}_MODEL" for p in ("ANTHROPIC", "OPENAI") for u in ("CHAT", "EXTRACT")]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_model_for_defaults_to_todays_models():
    assert model_for("anthropic", "chat") == MODEL == "claude-opus-5-5"
    assert model_for("anthropic", "extract") == MODEL
    assert model_for("openai", "chat") == OPENAI_MODEL == "gpt-4.1-mini"
    assert model_for("openai", "extract") == OPENAI_MODEL


def test_model_for_reads_only_its_variable(monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_OPENAI_EXTRACT_MODEL", "gpt-5-mini")
    assert model_for("openai", "extract") == "gpt-5-mini"
    assert model_for("openai", "chat") == OPENAI_MODEL
    assert model_for("anthropic", "extract") == MODEL
    assert model_for("anthropic", "chat") == MODEL


def test_model_for_ignores_blank_values(monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_ANTHROPIC_CHAT_MODEL", "  ")
    assert model_for("anthropic", "chat") == MODEL


def test_model_for_rejects_unknown_purpose():
    with pytest.raises(ValueError):
        model_for("anthropic", "vision")


def test_adapters_take_the_configured_model(monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_ANTHROPIC_CHAT_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("BRANCHPOINT_OPENAI_CHAT_MODEL", "gpt-5")
    assert AnthropicLLM("k").model == "claude-sonnet-5-5"
    assert OpenAILLM("k").model == "gpt-5"
    assert OpenAILLM("k", model="gpt-4.1").model == "gpt-4.1"


def test_image_block_rejects_unsupported_types():
    assert image_block("image/png", PNG)["source"] == {"type": "base64", "media_type": "image/png", "data": PNG}
    with pytest.raises(ValueError):
        image_block("image/svg+xml", PNG)


def test_response_input_turns_text_and_image_into_one_user_item():
    history = [
        {
            "role": "user",
            "content": [image_block("image/png", PNG), {"type": "text", "text": "¿Qué ves en el panel?"}],
        }
    ]
    items = response_input(history)
    assert items == [
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": f"data:image/png;base64,{PNG}", "detail": "auto"},
                {"type": "input_text", "text": "¿Qué ves en el panel?"},
            ],
        }
    ]


def test_response_input_keeps_plain_text_messages():
    history = [{"role": "user", "content": "Simula CyberDay"}]
    assert response_input(history) == history


def test_response_input_puts_tool_outputs_before_user_parts():
    history = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "{}"},
                {"type": "text", "text": "sigue"},
            ],
        }
    ]
    assert response_input(history) == [
        {"type": "function_call_output", "call_id": "c1", "output": "{}"},
        {"role": "user", "content": [{"type": "input_text", "text": "sigue"}]},
    ]
