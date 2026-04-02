"""Shared identity helpers used across workflow domains."""

from __future__ import annotations

from typing import NamedTuple


class EmployeeIdentity(NamedTuple):
    """Composite identity for disambiguating employees across tracker rows."""

    email: str
    work_location: str = ""
    job_title: str = ""
    status_change: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> EmployeeIdentity:
        """Build from a dict with employee_email / work_location / job_title / status_change keys."""
        return cls(
            email=str(data.get("employee_email", "") or data.get("staff_email", "")).strip(),
            work_location=str(data.get("work_location", "")).strip(),
            job_title=str(data.get("job_title", "")).strip(),
            status_change=str(data.get("status_change", "")).strip(),
        )

    def key(self) -> str:
        """Build a pipe-delimited composite identity key."""
        return identity_key(self.email, self.work_location, self.job_title, self.status_change)


def normalize_identity_part(value: str) -> str:
    """Lowercase-strip a single component of a composite identity key."""
    return str(value or "").strip().lower()


def identity_key(
    email: str,
    location: str = "",
    job_title: str = "",
    status_change: str = "",
) -> str:
    """Build a pipe-delimited composite identity key."""
    return "|".join([
        normalize_identity_part(email),
        normalize_identity_part(location),
        normalize_identity_part(job_title),
        normalize_identity_part(status_change),
    ])
