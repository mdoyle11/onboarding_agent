"""Helpers for extracting final assistant replies from agent messages."""

from __future__ import annotations

from json import JSONDecodeError, loads

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def extract_reply(messages: list[BaseMessage]) -> str:
    """Pull the last non-system assistant text from the messages."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts).strip()
            return str(content).strip()
    return "I was unable to complete your request."


def should_suppress_reply(messages: list[BaseMessage]) -> bool:
    """Suppress duplicate assistant text only when a Teams notification tool succeeded."""
    notification_tools = {
        "send_new_hire_card",
        "send_docusign_status_card",
        "send_background_clearance_card",
        "send_teams_channel_notification",
    }
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage) or msg.name not in notification_tools:
            continue
        if tool_message_succeeded(msg):
            return True
    return False


def tool_message_succeeded(message: ToolMessage) -> bool:
    """Best-effort parser for MCP tool results embedded in ToolMessage content."""
    content = message.content
    if isinstance(content, str):
        return _tool_text_succeeded(content)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and _tool_text_succeeded(text):
                    return True
    return False


def _tool_text_succeeded(text: str) -> bool:
    if '"success":true' in text.lower():
        return True
    try:
        parsed = loads(text)
        if isinstance(parsed, dict):
            return bool(parsed.get("success"))
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    inner_text = item.get("text")
                    if isinstance(inner_text, str):
                        try:
                            inner = loads(inner_text)
                            if isinstance(inner, dict) and inner.get("success") is True:
                                return True
                        except JSONDecodeError:
                            continue
    except JSONDecodeError:
        return False
    return False
