"""Shared identity helpers used across workflow domains."""

from __future__ import annotations


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
