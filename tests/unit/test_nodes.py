"""Tests for routing logic in agent nodes."""

from langchain_core.messages import AIMessage

from onboarding_agent.agent.nodes import after_error_handler, should_continue
from onboarding_agent.agent.state import default_state


def _state_with_messages(*msgs):
    s = default_state()
    s["messages"] = list(msgs)
    return s


def test_should_continue_routes_to_tool_executor_when_tool_calls():
    ai_msg = AIMessage(content="", tool_calls=[{"name": "find_employee_in_tracker", "args": {"employee_email": "x@y.com"}, "id": "1"}])
    state = _state_with_messages(ai_msg)
    assert should_continue(state) == "tool_executor"


def test_should_continue_routes_to_completion_when_no_tool_calls():
    ai_msg = AIMessage(content="Done!")
    state = _state_with_messages(ai_msg)
    assert should_continue(state) == "completion"


def test_should_continue_routes_to_error_handler_when_error():
    ai_msg = AIMessage(content="Done!")
    state = _state_with_messages(ai_msg)
    state["error_message"] = "Something broke"
    # error_message takes precedence over completion
    assert should_continue(state) == "error_handler"


def test_should_continue_routes_to_end_when_step_is_end():
    ai_msg = AIMessage(content="Done!")
    state = _state_with_messages(ai_msg)
    state["current_step"] = "end"
    assert should_continue(state) == "end"


def test_should_continue_empty_messages():
    state = default_state()
    assert should_continue(state) == "completion"


def test_after_error_handler_retries_below_threshold():
    state = default_state()
    state["retry_count"] = 1
    assert after_error_handler(state) == "agent"


def test_after_error_handler_ends_at_threshold():
    state = default_state()
    state["retry_count"] = 3
    assert after_error_handler(state) == "end"


def test_after_error_handler_ends_above_threshold():
    state = default_state()
    state["retry_count"] = 5
    assert after_error_handler(state) == "end"
