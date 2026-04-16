"""Tests for lightweight online eval decisions."""

from langchain_core.messages import ToolMessage

from onboarding_agent.observability.evals import evaluate_agent_response


def _result_by_name(results, name: str):
    return next(result for result in results if result.name == name)


def test_evals_pass_when_no_tool_requires_attention() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"success": true, "employee_email": "employee@example.com"}',
                tool_call_id="1",
                name="get_onboarding_status",
            )
        ],
        "The employee is on track.",
    )

    assert all(result.passed for result in results)


def test_clarification_eval_passes_when_reply_asks_clarifying_question() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"needs_clarification": true, "error": "Please specify whether this is a Separation or Transfer Out."}',
                tool_call_id="1",
                name="record_separation",
            )
        ],
        "Please specify whether this is a Separation or Transfer Out.",
    )

    assert _result_by_name(results, "clarification_response").passed is True
    assert _result_by_name(results, "no_write_after_clarification").passed is True


def test_clarification_eval_fails_when_reply_claims_action_without_question() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"needs_clarification": true, "error": "Multiple tracker rows matched this email."}',
                tool_call_id="1",
                name="update_tracker_stage",
            )
        ],
        "The Background Submission stage has been marked completed.",
    )

    assert _result_by_name(results, "clarification_response").passed is False


def test_no_write_after_clarification_fails_for_later_write_tool() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"needs_clarification": true, "error": "Multiple tracker rows matched this email."}',
                tool_call_id="1",
                name="find_employee_in_tracker",
            ),
            ToolMessage(
                content='{"success": true}',
                tool_call_id="2",
                name="update_tracker_stage",
            ),
        ],
        "Which row should I use?",
    )

    assert _result_by_name(results, "no_write_after_clarification").passed is False


def test_failure_truthfulness_fails_when_failed_tool_gets_success_claim() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"success": false, "error": "Graph write failed."}',
                tool_call_id="1",
                name="update_tracker_stage",
            )
        ],
        "The tracker has been updated successfully.",
    )

    assert _result_by_name(results, "failure_truthfulness").passed is False


def test_failure_truthfulness_passes_when_reply_acknowledges_failure() -> None:
    results = evaluate_agent_response(
        [
            ToolMessage(
                content='{"success": false, "error": "Graph write failed."}',
                tool_call_id="1",
                name="update_tracker_stage",
            )
        ],
        "I could not update the tracker because the Graph write failed.",
    )

    assert _result_by_name(results, "failure_truthfulness").passed is True
