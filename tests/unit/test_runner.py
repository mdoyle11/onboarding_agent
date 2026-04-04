"""Tests for the plain async agent loop in runner.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from onboarding_agent.agent.runner import (
    _format_session_context,
    _trim_messages,
    derive_session_context,
    run_agent,
)


def test_trim_messages_preserves_all_for_webhook():
    msgs = [SystemMessage(content="sys")] + [HumanMessage(content=f"msg {i}") for i in range(10)]
    result = _trim_messages(msgs, "pa_webhook")
    assert len(result) == 11


def test_trim_messages_limits_teams_queries():
    system = SystemMessage(content="sys")
    non_system = [HumanMessage(content=f"msg {i}") for i in range(10)]
    msgs = [system] + non_system
    result = _trim_messages(msgs, "teams_query")
    # Should keep system + last 4 non-system
    assert len(result) == 5
    assert isinstance(result[0], SystemMessage)
    assert result[1].content == "msg 6"


def test_trim_messages_drops_old_tool_messages_for_teams_queries():
    msgs = [
        SystemMessage(content="sys"),
        HumanMessage(content="hello"),
        AIMessage(content="", tool_calls=[{"name": "find_employee", "args": {}, "id": "1"}]),
        ToolMessage(content='{"found": true}', tool_call_id="1", name="find_employee"),
        AIMessage(content="I found the employee."),
    ]

    result = _trim_messages(msgs, "teams_query")

    assert len(result) == 4
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert isinstance(result[2], AIMessage)
    assert isinstance(result[3], AIMessage)


def test_trim_messages_short_list_unchanged():
    system = SystemMessage(content="sys")
    msgs = [system, HumanMessage(content="hello")]
    result = _trim_messages(msgs, "teams_query")
    assert len(result) == 2


def test_format_session_context_renders_small_system_message():
    message = _format_session_context(
        {"employee_email": "a@b.com", "intent": "check_onboarding_status"}
    )
    assert message is not None
    assert isinstance(message, SystemMessage)
    assert "employee_email" in str(message.content)
    assert "a@b.com" in str(message.content)


def test_format_session_context_skips_empty_values():
    assert _format_session_context({"employee_email": ""}) is None


def test_derive_session_context_uses_tool_results():
    messages = [
        ToolMessage(
            content='{"found": true, "employee_email": "alice@example.com", "name": "Alice", "submission_id": "sub-123"}',
            tool_call_id="1",
            name="get_onboarding_status",
        ),
        ToolMessage(
            content='{"success": true, "envelope_id": "env-123", "status": "sent"}',
            tool_call_id="2",
            name="send_docusign_envelope",
        ),
    ]

    result = derive_session_context(messages)

    assert result["submission_id"] == "sub-123"
    assert result["employee_email"] == "alice@example.com"
    assert result["employee_name"] == "Alice"
    assert result["envelope_id"] == "env-123"
    assert result["intent"] == "send_docusign_envelope"


def test_derive_session_context_uses_source_driven_employee_name_and_job_category():
    messages = [
        ToolMessage(
            content='{"success": true, "location": "Collier", "job_category": "Teacher"}',
            tool_call_id="1",
            name="check_staff_roster_capacity",
        ),
        ToolMessage(
            content='{"found": true, "employee_email": "alice@example.com", "name": "Alice"}',
            tool_call_id="2",
            name="get_onboarding_status",
        ),
    ]

    result = derive_session_context(messages, existing={"employee_name": "Alice Example"})

    assert result["employee_name"] == "Alice"
    assert result["job_category"] == "Teacher"
    assert result["work_location"] == "Collier"
    assert result["intent"] == "check_onboarding_status"


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
async def test_run_agent_injects_session_context_for_teams_queries():
    mock_response = AIMessage(content="Done!")
    mock_llm = AsyncMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with (
        patch("onboarding_agent.agent.runner._tools", [MagicMock()]),
        patch("onboarding_agent.agent.runner._tool_map", {"tool": MagicMock()}),
        patch("onboarding_agent.agent.runner._build_llm", return_value=mock_llm),
    ):
        await run_agent(
            [HumanMessage(content="hello")],
            trigger_source="teams_query",
            session_context={"employee_email": "a@b.com", "intent": "check_onboarding_status"},
        )

    invoked_messages = mock_llm.ainvoke.await_args.args[0]
    assert isinstance(invoked_messages[0], SystemMessage)
    assert isinstance(invoked_messages[1], SystemMessage)
    assert "a@b.com" in str(invoked_messages[1].content)


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
