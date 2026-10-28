from __future__ import annotations

from subscription_gateway.compat.openai_chat import messages_to_prompt


def test_prompt_conversion_preserves_role_markers() -> None:
    prompt = messages_to_prompt(
        [
            {"role": "system", "content": "System text"},
            {"role": "developer", "content": "Developer text"},
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Prior answer"},
        ]
    )
    assert prompt == (
        "[SYSTEM]\nSystem text\n\n"
        "[DEVELOPER]\nDeveloper text\n\n"
        "[USER]\nQuestion\n\n"
        "[ASSISTANT]\nPrior answer"
    )


def test_prompt_conversion_renders_responses_text_parts() -> None:
    prompt = messages_to_prompt(
        [
            {"role": "user", "content": [{"type": "input_text", "text": "Question"}]},
            {"role": "assistant", "content": [{"type": "output_text", "text": "Answer"}]},
        ]
    )
    assert prompt == "[USER]\nQuestion\n\n[ASSISTANT]\nAnswer"
