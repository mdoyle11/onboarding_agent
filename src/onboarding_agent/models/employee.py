"""Employee and onboarding record models."""

from datetime import date
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


class Employee(BaseModel):
    name: str
    email: EmailStr
    start_date: date
    department: str
    manager_email: EmailStr

    @field_validator("name", "department")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class OnboardingRecord(BaseModel):
    employee: Employee
    forms_submission_id: str = ""
    forms_data_raw: dict[str, Any] = {}
    excel_row_id: str = ""
    excel_status: str = "Pending"
    docusign_envelope_id: str = ""
    docusign_envelope_status: str = ""
    docusign_draft_exists: bool = False
    teams_notification_sent: bool = False
