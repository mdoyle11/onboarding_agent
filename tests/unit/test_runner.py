"""Tests for the plain async agent loop in runner.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from onboarding_agent.agent.runner import _trim_messages, run_agent


def test_trim_messages_preserves_all_for_webhook():
    msgs = [SystemMessage(content="sys")] + [HumanMessage(content=f"msg {i}") for i in range(10)]
    result = _trim_messages(msgs, "pa_webhook")
    assert len(result) == 11


def test_trim_messages_limits_teams_queries():
    system = SystemMessage(content="sys")
    non_system = [HumanMessage(content=f"msg {i}") for i in range(10)]
    msgs = [system] + non_system
    result = _trim_messages(msgs, "teams_query")
    # Should keep system + last 5 non-system
    assert len(result) == 6
    assert isinstance(result[0], SystemMessage)
    assert result[1].content == "msg 5"


def test_trim_messages_short_list_unchanged():
    system = SystemMessage(content="sys")
    msgs = [system, HumanMessage(content="hello")]
    result = _trim_messages(msgs, "teams_query")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_run_agent_returns_messages_when_no_tool_calls():
    mock_response = AIMessage(content="Done!")
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with (
        patch("onboarding_agent.agent.runner._tools", [MagicMock()]),
        patch("onboarding_agent.agent.runner._tool_map", {"tool": MagicMock()}),
        patch("onboarding_agent.agent.runner._build_llm", return_value=mock_llm),
    ):
        result = await run_agent([HumanMessage(content="hello")])

    assert len(result) == 3  # system + human + ai
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[-1], AIMessage)
    assert result[-1].content == "Done!"


@pytest.mark.asyncio
async def test_run_agent_executes_tool_calls():
    tool_response = AIMessage(
        content="",
        tool_calls=[{"name": "find_employee_in_tracker", "args": {"email": "a@b.com"}, "id": "1"}],
    )
    final_response = AIMessage(content="Found the employee.")
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=[tool_response, final_response])

    mock_tool = MagicMock()
    mock_tool.arun = AsyncMock(return_value='{"found": true}')

    with (
        patch("onboarding_agent.agent.runner._tools", [mock_tool]),
        patch("onboarding_agent.agent.runner._tool_map", {"find_employee_in_tracker": mock_tool}),
        patch("onboarding_agent.agent.runner._build_llm", return_value=mock_llm),
    ):
        result = await run_agent([HumanMessage(content="find alice")])

    # system + human + ai(tool_call) + tool_message + ai(final)
    assert len(result) == 5
    assert result[-1].content == "Found the employee."


@pytest.mark.asyncio
async def test_run_agent_retries_on_llm_failure():
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(
        side_effect=[Exception("API error"), AIMessage(content="Recovered")]
    )

    with (
        patch("onboarding_agent.agent.runner._tools", [MagicMock()]),
        patch("onboarding_agent.agent.runner._tool_map", {}),
        patch("onboarding_agent.agent.runner._build_llm", return_value=mock_llm),
    ):
        result = await run_agent([HumanMessage(content="hello")], max_retries=3)

    assert result[-1].content == "Recovered"


@pytest.mark.asyncio
async def test_run_agent_raises_after_max_retries():
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))

    with (
        patch("onboarding_agent.agent.runner._tools", [MagicMock()]),
        patch("onboarding_agent.agent.runner._tool_map", {}),
        patch("onboarding_agent.agent.runner._build_llm", return_value=mock_llm),
        pytest.raises(Exception, match="API error"),
    ):
        await run_agent([HumanMessage(content="hello")], max_retries=2)


@pytest.mark.asyncio
async def test_run_agent_raises_if_not_initialized():
    with pytest.raises(RuntimeError, match="Agent not initialized"):
        await run_agent([HumanMessage(content="hello")])
