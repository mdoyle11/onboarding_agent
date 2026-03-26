"""Adaptive Card templates for Teams notifications.

Each function returns a dict representing an Adaptive Card JSON payload,
ready to be attached to an Agents SDK Activity.
"""

from __future__ import annotations

from typing import Any


def new_hire_card(
    employee_name: str,
    employee_email: str,
    start_date: str,
    department: str,
    location: str,
    manager_email: str,
    summary: str,
    email_sent: bool = False,
    docusign_sent: bool = False,
) -> dict[str, Any]:
    """Card sent when a new hire webhook triggers the pipeline."""
    actions: list[dict[str, Any]] = []
    if email_sent:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "\u2713 Welcome Email Sent",
                "isEnabled": False,
                "data": {"action": "send_onboarding_email", "employee_email": employee_email},
            }
        )
    else:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "Send Welcome Email",
                "data": {"action": "send_onboarding_email", "employee_email": employee_email},
            }
        )

    if docusign_sent:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "\u2713 Offer Letter Sent",
                "isEnabled": False,
                "data": {"action": "send_docusign", "employee_email": employee_email},
            }
        )
    else:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "Send Offer Letter",
                "data": {"action": "send_docusign", "employee_email": employee_email},
            }
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
                            {"type": "TextBlock", "text": "New Hire Added", "weight": "Bolder", "size": "Medium", "wrap": True},
                            {"type": "TextBlock", "text": f"{employee_name} ({employee_email})", "spacing": "None", "isSubtle": True, "wrap": True},
                        ],
                    },
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Start Date", "value": start_date or "TBD"},
                    {"title": "Department", "value": department or "N/A"},
                    {"title": "Location", "value": location or "N/A"},
                    {"title": "Manager", "value": manager_email or "N/A"},
                    {"title": "Welcome Email", "value": "Sent \u2713" if email_sent else "Ready"},
                    {"title": "Offer Letter", "value": "Sent \u2713" if docusign_sent else "Ready"},
                ],
            },
            {"type": "TextBlock", "text": " ", "separator": True},
            {"type": "TextBlock", "text": summary, "wrap": True},
        ],
        "actions": actions,
    }


def docusign_status_card(employee_email: str, envelope_id: str, status: str, summary: str) -> dict[str, Any]:
    """Card sent when a DocuSign envelope status changes."""
    status_icon = {
        "completed": "\u2705",
        "sent": "\U0001f4e8",
        "delivered": "\U0001f4ec",
        "declined": "\u274c",
        "voided": "\u26d4",
    }.get(status.lower(), "\U0001f4cb")

    status_color = "Good" if status.lower() == "completed" else "Default"

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
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
            {"type": "FactSet", "facts": [{"title": "Employee", "value": employee_email or "Unknown"}, {"title": "Envelope", "value": envelope_id[:8] + "..." if len(envelope_id) > 8 else envelope_id}]},
            {"type": "TextBlock", "text": " ", "separator": True},
            {"type": "TextBlock", "text": summary, "wrap": True},
        ],
    }


def background_clearance_card(employee_name: str, employee_email: str, summary: str) -> dict[str, Any]:
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
            {"type": "TextBlock", "text": summary, "wrap": True},
        ],
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
