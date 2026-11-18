"""Content model: messages and content blocks (ADR-0002 D3)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from agentreins.types.content import (
    ContentBlock,
    ImageBlock,
    Message,
    ReasoningBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _conversation() -> list[Message]:
    """The two-parallel-tool-calls example from ADR-0002 D3."""
    return [
        Message.user("How much A12 stock do we have?"),
        Message(
            role="assistant",
            content=[
                ReasoningBlock(text="Check both warehouses.", provider_signature="sig"),
                TextBlock(text="Let me check both warehouses."),
                ToolUseBlock(
                    id="c1",
                    provider_id="call_x",
                    name="get_inventory",
                    arguments={"sku": "A12", "wh": "north"},
                ),
                ToolUseBlock(
                    id="c2", name="get_inventory", arguments={"sku": "A12", "wh": "south"}
                ),
            ],
        ),
        Message(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="c1", content=[TextBlock(text="40")]),
                ToolResultBlock(tool_use_id="c2", content=[TextBlock(text="0")], is_error=False),
            ],
        ),
    ]


def test_messages_round_trip_through_json() -> None:
    for message in _conversation():
        assert Message.model_validate_json(message.model_dump_json()) == message


def test_blocks_are_parsed_by_their_type_field() -> None:
    adapter: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)
    block = adapter.validate_python({"type": "tool_use", "id": "c1", "name": "t"})
    assert isinstance(block, ToolUseBlock)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "video", "url": "x"})


def test_messages_are_frozen() -> None:
    message = Message.user("hi")
    with pytest.raises(ValidationError):
        message.role = "assistant"  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TextBlock.model_validate({"type": "text", "text": "hi", "txet": "typo"})


@pytest.mark.parametrize(
    ("role", "block"),
    [
        ("user", ToolUseBlock(id="c1", name="t")),
        ("user", ReasoningBlock(text="thinking")),
        ("assistant", ToolResultBlock(tool_use_id="c1", content=[])),
    ],
)
def test_blocks_must_match_role(role: str, block: ContentBlock) -> None:
    with pytest.raises(ValidationError, match="cannot contain"):
        Message.model_validate({"role": role, "content": [block.model_dump()]})


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "system", "content": []})


def test_image_needs_exactly_one_source() -> None:
    ImageBlock(media_type="image/png", url="https://example.com/a.png")
    ImageBlock(media_type="image/png", data="aGk=")
    with pytest.raises(ValidationError, match="exactly one"):
        ImageBlock(media_type="image/png")
    with pytest.raises(ValidationError, match="exactly one"):
        ImageBlock(media_type="image/png", data="aGk=", url="https://example.com/a.png")


def test_unparseable_arguments_keep_the_raw_text() -> None:
    block = ToolUseBlock(id="c1", name="t", raw_arguments="{bad", parse_error="Expecting value")
    assert block.arguments == {}
    with pytest.raises(ValidationError, match="raw_arguments"):
        ToolUseBlock(id="c1", name="t", parse_error="Expecting value")


def test_message_text_joins_text_blocks_only() -> None:
    message = Message(
        role="assistant",
        content=[TextBlock(text="a"), ToolUseBlock(id="c1", name="t"), TextBlock(text="b")],
    )
    assert message.text == "ab"
    assert Message.assistant("hi").text == "hi"
