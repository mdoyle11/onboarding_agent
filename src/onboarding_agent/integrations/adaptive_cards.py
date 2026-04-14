"""Adaptive Card templates for Teams notifications.

Each function returns a dict representing an Adaptive Card JSON payload,
ready to be attached to an Agents SDK Activity.
"""

from __future__ import annotations

from typing import Any

from onboarding_agent.domain.formatting import format_date


def _action_button(
    action: str,
    title: str,
    completed_title: str,
    is_complete: bool,
    employee_email: str,
    submission_id: str = "",
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> dict[str, Any]:
    """Build an Adaptive Card Action.Submit button with optional completed state."""
    data = {
        "action": action,
        "employee_email": employee_email,
        "submission_id": submission_id,
        "work_location": work_location,
        "job_title": job_title,
        "status_change": status_change,
    }
    if is_complete:
        return {"type": "Action.Submit", "title": completed_title, "isEnabled": False, "data": data}
    return {"type": "Action.Submit", "title": title, "data": data}


def new_hire_card(
    employee_name: str,
    employee_email: str,
    summary: str,
    submission_id: str = "",
    title: str = "",
    status_change: str = "",
    requested_start_date: str = "",
    job_title: str = "",
    work_location: str = "",
    requesting_manager: str = "",
    email_sent: bool = False,
    docusign_draft_created: bool = False,
    allow_email_action: bool = True,
    allow_docusign_action: bool = True,
) -> dict[str, Any]:
    """Card sent when a new hire webhook triggers the pipeline."""
    card_title = title or f"{status_change or 'Submission'} Requested"
    formatted_requested_start_date = format_date(requested_start_date) or requested_start_date
    identity = dict(
        employee_email=employee_email,
        submission_id=submission_id,
        work_location=work_location,
        job_title=job_title,
        status_change=status_change,
    )
    actions: list[dict[str, Any]] = []
    if allow_email_action:
        actions.append(_action_button("send_onboarding_email", "Send Welcome Email", "\u2713 Welcome Email Sent", email_sent, **identity))
    if allow_docusign_action:
        actions.append(
            _action_button(
                "create_docusign_draft",
                "Create Offer Letter Draft",
                "\u2713 Offer Letter Draft Created",
                docusign_draft_created,
                **identity,
            )
        )

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": "\U0001f389", "size": "Large"}]},
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {"type": "TextBlock", "text": card_title, "weight": "Bolder", "size": "Medium", "wrap": True},
                            {"type": "TextBlock", "text": f"{employee_name} ({employee_email})", "spacing": "None", "isSubtle": True, "wrap": True},
                        ],
                    },
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Requested Start Date", "value": formatted_requested_start_date or "TBD"},
                    {"title": "Job Title", "value": job_title or "N/A"},
                    {"title": "Work Location", "value": work_location or "N/A"},
                    {"title": "Requesting Manager", "value": requesting_manager or "N/A"},
                    {"title": "Status Change", "value": status_change or "N/A"},
                    {"title": "Staff Name", "value": employee_name or "N/A"},
                    {"title": "Staff Email", "value": employee_email or "N/A"},
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {"type": "TextBlock", "text": summary, "wrap": True},
        ],
        "actions": actions,
    }


def docusign_status_card(
    employee_email: str,
    envelope_id: str,
    status: str,
    summary: str,
    submission_id: str = "",
    employee_name: str = "",
    roster_added: bool = False,
    job_category: str = "",
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
    review_url: str = "",
    allow_send_action: bool = False,
) -> dict[str, Any]:
    """Card sent when a DocuSign envelope status changes."""
    status_icon = {
        "completed": "\u2705",
        "sent": "\U0001f4e8",
        "delivered": "\U0001f4ec",
        "declined": "\u274c",
        "voided": "\u26d4",
    }.get(status.lower(), "\U0001f4cb")

    status_color = "Good" if status.lower() == "completed" else "Default"
    actions: list[dict[str, Any]] = []
    body: list[dict[str, Any]] = [
        {
            "type": "ColumnSet",
            "columns": [
                {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": status_icon, "size": "Large"}]},
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": "DocuSign Update", "weight": "Bolder", "size": "Medium", "wrap": True},
                        {"type": "TextBlock", "text": f"Envelope status: **{status}**", "spacing": "None", "color": status_color, "wrap": True},
                    ],
                },
            ],
        },
        {"type": "TextBlock", "text": " ", "separator": True},
        {
            "type": "FactSet",
            "facts": [
                {"title": "Employee", "value": employee_name or employee_email or "Unknown"},
                {"title": "Email", "value": employee_email or "Unknown"},
                {"title": "Location", "value": work_location or "N/A"},
                {"title": "Job Title", "value": job_title or "N/A"},
                {"title": "Envelope", "value": envelope_id[:8] + "..." if len(envelope_id) > 8 else envelope_id},
            ],
        },
        {"type": "TextBlock", "text": " ", "separator": True},
        {"type": "TextBlock", "text": summary, "wrap": True},
    ]

    if review_url:
        actions.append(
            {
                "type": "Action.OpenUrl",
                "title": "Review Offer Letter Draft",
                "url": review_url,
            }
        )

    if status.lower() == "created":
        actions.append(
            _action_button(
                "refresh_review_link",
                "Refresh Review Link",
                "Refresh Review Link",
                False,
                employee_email=employee_email,
                submission_id=submission_id,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
        )

    if status.lower() == "created" and allow_send_action:
        actions.append(
            _action_button(
                "send_docusign",
                "Send Offer Letter",
                "\u2713 Offer Letter Sent",
                False,
                employee_email=employee_email,
                submission_id=submission_id,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
        )

    if status.lower() == "completed":
        body.extend(
            [
                {"type": "TextBlock", "text": " ", "separator": True},
                {
                    "type": "Input.Text",
                    "id": "job_category",
                    "label": "Staff roster job category",
                    "placeholder": "Enter the exact Group/category value",
                    "value": job_category,
                    "isRequired": not roster_added,
                },
            ]
        )
        actions.append(_action_button(
            "add_to_staff_roster", "Add To Staff Roster", "\u2713 Added To Staff Roster",
            roster_added, employee_email=employee_email, submission_id=submission_id, work_location=work_location,
            job_title=job_title, status_change=status_change,
        ))

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
        "actions": actions,
    }


def background_clearance_card(
    employee_name: str,
    employee_email: str,
    summary: str,
    work_location: str = "",
    job_title: str = "",
) -> dict[str, Any]:
    """Card sent when a background clearance form is submitted."""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": "\U0001f50e", "size": "Large"}]},
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {"type": "TextBlock", "text": "Background Clearance Submitted", "weight": "Bolder", "size": "Medium", "wrap": True},
                            {"type": "TextBlock", "text": f"{employee_name} ({employee_email})", "spacing": "None", "isSubtle": True, "wrap": True},
                        ],
                    },
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Employee", "value": employee_name or employee_email or "Unknown"},
                    {"title": "Email", "value": employee_email or "Unknown"},
                    {"title": "Location", "value": work_location or "N/A"},
                    {"title": "Job Title", "value": job_title or "N/A"},
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {"type": "TextBlock", "text": summary, "wrap": True},
        ],
    }


def clear_to_start_card(
    employee_email: str,
    employee_name: str = "",
    submission_id: str = "",
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
    requested_start_date: str = "",
    requesting_manager: str = "",
    email_sent: bool = False,
) -> dict[str, Any]:
    """Card used by HR to collect Clear to Start email fields."""
    formatted_date = format_date(requested_start_date) or requested_start_date
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": "\u2705", "size": "Large"}]},
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {"type": "TextBlock", "text": "Clear to Start Email", "weight": "Bolder", "size": "Medium", "wrap": True},
                            {"type": "TextBlock", "text": f"{employee_name or employee_email} ({employee_email})", "spacing": "None", "isSubtle": True, "wrap": True},
                        ],
                    },
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Clear Date", "value": formatted_date or "Today unless changed below"},
                    {"title": "Job Title", "value": job_title or "N/A"},
                    {"title": "Work Location", "value": work_location or "N/A"},
                    {"title": "Hiring Manager", "value": requesting_manager or "N/A"},
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {
                "type": "Input.Date",
                "id": "clear_to_start_date",
                "label": "Clear to Start date",
                "value": requested_start_date,
                "isRequired": True,
                "errorMessage": "Enter the Clear to Start date.",
            },
            {
                "type": "Input.Text",
                "id": "treasurer_name",
                "label": "Treasurer name",
                "placeholder": "Taylor Treasurer",
                "isRequired": True,
                "errorMessage": "Enter the Treasurer name.",
            },
            {
                "type": "Input.Text",
                "id": "treasurer_email",
                "label": "Treasurer email",
                "placeholder": "treasurer@example.com",
                "style": "Email",
                "isRequired": True,
                "errorMessage": "Enter the Treasurer email.",
            },
            {
                "type": "Input.Text",
                "id": "hiring_manager_email",
                "label": "Hiring Manager email",
                "placeholder": "manager@example.com",
                "style": "Email",
                "isRequired": True,
                "errorMessage": "Enter the Hiring Manager email.",
            },
            {
                "type": "Input.Text",
                "id": "cc_emails",
                "label": "Additional CC emails",
                "placeholder": "optional@example.com, another@example.com",
                "isMultiline": False,
            },
        ],
        "actions": [
            _action_button(
                "send_clear_to_start",
                "Send Clear to Start Email",
                "\u2713 Clear to Start Email Sent",
                email_sent,
                employee_email=employee_email,
                submission_id=submission_id,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
            )
        ],
    }


def separation_card(
    employee_name: str,
    employee_email: str,
    summary: str,
    submission_id: str = "",
    title: str = "",
    status_change: str = "",
    requested_start_date: str = "",
    job_title: str = "",
    work_location: str = "",
    requesting_manager: str = "",
    action_name: str = "",
    action_label: str = "",
    action_completed_label: str = "",
    action_completed: bool = False,
    job_category: str = "",
) -> dict[str, Any]:
    """Card sent when a separation-category webhook triggers the pipeline."""
    card_title = title or f"{status_change or 'Submission'} Requested"
    formatted_date = format_date(requested_start_date) or requested_start_date
    identity = dict(
        employee_email=employee_email,
        submission_id=submission_id,
        work_location=work_location,
        job_title=job_title,
        status_change=status_change,
    )

    body: list[dict[str, Any]] = [
        {
            "type": "ColumnSet",
            "columns": [
                {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": "\U0001f4cb", "size": "Large"}]},
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": card_title, "weight": "Bolder", "size": "Medium", "wrap": True},
                        {"type": "TextBlock", "text": f"{employee_name} ({employee_email})", "spacing": "None", "isSubtle": True, "wrap": True},
                    ],
                },
            ],
        },
        {"type": "TextBlock", "text": " ", "separator": True},
        {
            "type": "FactSet",
            "facts": [
                {"title": "Effective Date", "value": formatted_date or "TBD"},
                {"title": "Status Change", "value": status_change or "N/A"},
                {"title": "Job Title", "value": job_title or "N/A"},
                {"title": "Work Location", "value": work_location or "N/A"},
                {"title": "Requesting Manager", "value": requesting_manager or "N/A"},
                {"title": "Staff Name", "value": employee_name or "N/A"},
                {"title": "Staff Email", "value": employee_email or "N/A"},
            ],
        },
        {"type": "TextBlock", "text": " ", "separator": True},
        {"type": "TextBlock", "text": summary, "wrap": True},
    ]

    actions: list[dict[str, Any]] = []
    if action_name:
        if action_name == "add_to_staff_roster":
            body.extend([
                {"type": "TextBlock", "text": " ", "separator": True},
                {
                    "type": "Input.Text",
                    "id": "job_category",
                    "label": "Staff roster job category",
                    "placeholder": "Enter the exact Group/category value",
                    "value": job_category,
                    "isRequired": not action_completed,
                },
            ])
        actions.append(_action_button(
            action_name,
            action_label or "Process",
            action_completed_label or "\u2713 Processed",
            action_completed,
            **identity,
        ))

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
        "actions": actions,
    }


def generic_notification_card(title: str, message: str) -> dict[str, Any]:
    """Fallback card for general notifications."""
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "TextBlock", "text": " ", "separator": True},
            {"type": "TextBlock", "text": message, "wrap": True},
        ],
    }
