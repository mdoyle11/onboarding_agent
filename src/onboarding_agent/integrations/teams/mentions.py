"""Helpers for Teams mention detection and message cleanup."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_mention_text(value: str) -> str:
    """Normalize Teams mention text/names for reliable comparisons."""
    return "".join(ch.lower() for ch in value if ch.isalnum())


def is_mentioned(activity: Any) -> bool:
    """Check if the incoming message explicitly mentions the bot."""
    bot_id = activity.recipient.id if activity.recipient else ""
    bot_name = (getattr(activity.recipient, "name", "") or "").strip().lower()
    normalized_bot_name = _normalize_mention_text(bot_name)
    activity_text = (activity.text or "").strip().lower()
    mention_debug: list[dict[str, str]] = []
    for mention in activity.get_mentions():
        mentioned = getattr(mention, "mentioned", None)
        mentioned_id = getattr(mentioned, "id", "") if mentioned else ""
        mentioned_name = (getattr(mentioned, "name", "") if mentioned else "").strip().lower()
        mention_text = (getattr(mention, "text", "") or "").strip().lower()
        normalized_mentioned_name = _normalize_mention_text(mentioned_name)
        normalized_mention_text = _normalize_mention_text(mention_text)
        mention_debug.append(
            {
                "mentioned_id": mentioned_id,
                "mentioned_name": mentioned_name,
                "mention_text": mention_text,
            }
        )

        if bot_id and mentioned_id == bot_id:
            logger.info("Bot mention matched by recipient id: %s", mention_debug)
            return True
        if normalized_bot_name and normalized_mentioned_name == normalized_bot_name:
            logger.info("Bot mention matched by recipient name: %s", mention_debug)
            return True
        if normalized_mention_text and normalized_bot_name and normalized_bot_name in normalized_mention_text:
            logger.info("Bot mention matched by mention text: %s", mention_debug)
            return True
        if mention_text and mention_text in activity_text:
            logger.info("Bot mention matched by activity text: %s", mention_debug)
            return True
    logger.info(
        "Bot mention not detected: recipient_id=%s recipient_name=%s mentions=%s activity_text=%r",
        bot_id,
        bot_name,
        mention_debug,
        activity_text[:200],
    )
    return False


def strip_mention(activity: Any) -> str:
    """Remove mention text from an incoming activity."""
    text = activity.text or ""
    for mention in activity.get_mentions():
        mention_text = getattr(mention, "text", "") or ""
        if mention_text:
            text = text.replace(mention_text, "")
    return text.strip()
