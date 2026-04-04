from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.integrations.teams.proactive import send_proactive_message


@pytest.mark.asyncio
async def test_send_proactive_message_sets_reply_to_id_on_outgoing_activity():
    adapter = AsyncMock()
    ref = SimpleNamespace(
        get_continuation_activity=lambda: SimpleNamespace(
            id="old-id",
            reply_to_id=None,
            conversation=SimpleNamespace(id="19:channel@thread.tacv2"),
        )
    )
    sent_activities: list[object] = []

    async def _continue_conversation(_bot_app_id, continuation_activity, callback):
        turn_context = AsyncMock()

        async def _send_activity(activity):
            sent_activities.append(activity)
            return SimpleNamespace(id="msg-123")

        turn_context.send_activity.side_effect = _send_activity
        assert continuation_activity.reply_to_id == "root-msg"
        assert continuation_activity.conversation.id == "19:channel@thread.tacv2;messageid=root-msg"
        await callback(turn_context)

    adapter.continue_conversation.side_effect = _continue_conversation

    with (
        patch("onboarding_agent.integrations.teams.proactive._ensure_adapter", return_value=adapter),
        patch("onboarding_agent.integrations.teams.proactive.get_conversation_reference", new=AsyncMock(return_value=ref)),
        patch("onboarding_agent.integrations.teams.proactive.bot_app_id", "bot-id"),
    ):
        result = await send_proactive_message(
            "channel-1",
            "hello",
            card={"type": "AdaptiveCard", "version": "1.5", "body": []},
            reply_to_id="root-msg",
        )

    assert result["success"] is True
    assert sent_activities
    assert getattr(sent_activities[0], "reply_to_id", "") == "root-msg"
