"""OnboardingState TypedDict - the single source of truth for graph execution."""

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class OnboardingState(TypedDict):
    # Agent loop messages (append-only via reducer)
    messages: Annotated[list[AnyMessage], add_messages]

    # Trigger context
    trigger_source: str          # "teams_query" | "pa_webhook"
    triggered_by_user_id: str    # Teams AAD user ID (empty for automated runs)

    # Employee fields
    employee_email: str
    employee_name: str
    employee_start_date: str
    employee_department: str
    employee_location: str
    employee_manager_email: str

    # Forms
    forms_submission_id: str
    forms_data_raw: dict[str, Any]

    # Excel tracker
    excel_row_id: str
    excel_status: str

    # DocuSign
    docusign_envelope_id: str
    docusign_envelope_status: str   # "created"|"sent"|"delivered"|"completed"|"voided"
    docusign_draft_exists: bool

    # Teams
    teams_notification_sent: bool
    teams_channel_id: str

    # Control flow
    current_step: str
    error_message: str
    retry_count: int
    completed: bool


def default_state() -> dict[str, Any]:
    """Return a state dict with all defaults — avoids KeyError in nodes."""
    return {
        "messages": [],
        "trigger_source": "",
        "triggered_by_user_id": "",
        "employee_email": "",
        "employee_name": "",
        "employee_start_date": "",
        "employee_department": "",
        "employee_location": "",
        "employee_manager_email": "",
        "forms_submission_id": "",
        "forms_data_raw": {},
        "excel_row_id": "",
        "excel_status": "",
        "docusign_envelope_id": "",
        "docusign_envelope_status": "",
        "docusign_draft_exists": False,
        "teams_notification_sent": False,
        "teams_channel_id": "",
        "current_step": "",
        "error_message": "",
        "retry_count": 0,
        "completed": False,
    }
