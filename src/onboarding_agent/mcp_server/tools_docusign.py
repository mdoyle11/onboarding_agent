"""DocuSign tools — envelope draft creation, sending, and status checks."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from onboarding_agent.mcp_server.clients import docusign as _docusign
from onboarding_agent.mcp_server.clients import tracker as _tracker

logger = logging.getLogger(__name__)


async def _resolve_unsent_offer_letter_match(employee_email: str) -> dict[str, Any]:
    tracker_result = await _tracker().find_employee_in_tracker(employee_email)
    matches = tracker_result.get("matches", [])
    if not tracker_result.get("multiple_matches") or not isinstance(matches, list) or not matches:
        return {}

    unsent_matches: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        location = str(match.get("location", "") or "")
        job_title = str(match.get("job_title", "") or "")
        status_change = str(match.get("status_change", "") or "")
        stages_result = await _tracker().get_employee_stages(
            employee_email,
            location=location,
            job_title=job_title,
            status_change=status_change,
        )
        stages = stages_result.get("stages", {})
        if not isinstance(stages, dict):
            continue
        sent_offer_letter = str(stages.get("Sent Offer Letter", "") or "").strip()
        if not sent_offer_letter:
            unsent_matches.append({
                "location": location,
                "job_title": job_title,
                "status_change": status_change,
            })

    if len(unsent_matches) == 1:
        return {"resolved": True, **unsent_matches[0], "matches": matches}
    return {"resolved": False, "matches": matches}


async def _resolve_tracker_record_for_offer_letter(
    *,
    employee_email: str,
    work_location: str = "",
    job_title: str = "",
    status_change: str = "",
    submission_id: str = "",
) -> dict[str, Any]:
    tracker = _tracker()
    submission_id = submission_id.strip()
    if submission_id:
        result = await tracker.find_employee_in_tracker(employee_email, submission_id=submission_id)
        if result.get("found") or result.get("multiple_matches"):
            return result

    attempts = [
        {
            "location": work_location,
            "job_title": job_title,
            "status_change": status_change,
        },
        {
            "location": work_location,
            "job_title": "",
            "status_change": status_change,
        },
        {
            "location": work_location,
            "job_title": "",
            "status_change": "",
        },
        {
            "location": "",
            "job_title": "",
            "status_change": "",
        },
    ]
    seen: set[tuple[str, str, str]] = set()
    for attempt in attempts:
        key = (
            attempt["location"].strip().lower(),
            attempt["job_title"].strip().lower(),
            attempt["status_change"].strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result = await tracker.find_employee_in_tracker(
            employee_email,
            location=attempt["location"],
            job_title=attempt["job_title"],
            status_change=attempt["status_change"],
        )
        if result.get("found") or result.get("multiple_matches"):
            return result
    return {"found": False, "error": f"Tracker row not found for {employee_email}."}


def register(mcp: FastMCP) -> None:
    """Register all DocuSign tools on the given FastMCP instance."""

    @mcp.tool()
    async def check_docusign_draft_exists(
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Check whether a matching DocuSign draft exists for one workflow row.

        Use this before sending an offer letter. If duplicate tracker rows share
        the same email, pass `work_location`, `job_title`, and/or
        `status_change` when available. Pass `submission_id` when available,
        because it lets this tool refresh the current tracker row before checking
        DocuSign. When only one matching tracker row still needs an offer
        letter, this tool can resolve it automatically; otherwise it returns an
        ambiguity error instead of guessing.
        """
        if submission_id or work_location or job_title or status_change:
            tracker_record = await _resolve_tracker_record_for_offer_letter(
                employee_email=employee_email,
                work_location=work_location,
                job_title=job_title,
                status_change=status_change,
                submission_id=submission_id,
            )
            if not tracker_record.get("found"):
                return {
                    "exists": False,
                    "envelope_id": "",
                    "multiple_matches": bool(tracker_record.get("multiple_matches", False)),
                    "matches": tracker_record.get("matches", []),
                    "submission_id": submission_id,
                    "error": str(tracker_record.get("error", f"Tracker row not found for {employee_email}.")),
                }
            work_location = str(tracker_record.get("location", "") or work_location or "")
            job_title = str(tracker_record.get("job_title", "") or job_title or "")
            status_change = str(tracker_record.get("status_change", "") or status_change or "")
            submission_id = str(tracker_record.get("submission_id", "") or submission_id or "")
        else:
            resolved = await _resolve_unsent_offer_letter_match(employee_email)
            if resolved.get("resolved"):
                work_location = str(resolved.get("location", "") or "")
                job_title = str(resolved.get("job_title", "") or "")
                status_change = str(resolved.get("status_change", "") or "")
            elif resolved.get("matches"):
                return {
                    "exists": False,
                    "envelope_id": "",
                    "multiple_matches": True,
                    "matches": resolved.get("matches", []),
                    "error": (
                        "Multiple tracker rows match this email and more than one still needs an offer letter. "
                        "Provide work_location, job_title, or status_change before checking DocuSign."
                    ),
                }
        client = _docusign()
        result = await client.check_draft_exists(employee_email, work_location, job_title, status_change)
        if work_location:
            result["work_location"] = work_location
        if job_title:
            result["job_title"] = job_title
        if status_change:
            result["status_change"] = status_change
        if submission_id:
            result["submission_id"] = submission_id
        return result

    @mcp.tool()
    async def create_docusign_envelope_draft(
        employee_name: str,
        employee_email: str,
        start_date: str,
        position: str,
        work_location: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Create a DocuSign offer-letter draft, but do not send it yet.

        This uses the configured template and returns an envelope in `created`
        status. Call `send_docusign_envelope` afterward to actually send it.
        """
        client = _docusign()
        return await client.create_envelope_draft(
            employee_name,
            employee_email,
            start_date,
            position,
            work_location,
            status_change,
            submission_id,
        )

    @mcp.tool()
    async def create_offer_letter_draft_from_tracker(
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Create or reuse an offer-letter draft from the current tracker row.

        Prefer this for natural-language requests like "create the offer letter
        draft". It resolves the tracker row first, then uses the tracker's
        current start date, job title, location, and workflow status to create
        the DocuSign draft. Pass `submission_id` when available because it is
        the most stable workflow key. If a matching draft already exists, this
        tool returns it instead of creating a duplicate.
        """
        tracker_record = await _resolve_tracker_record_for_offer_letter(
            employee_email=employee_email,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )
        if not tracker_record.get("found"):
            return {
                "success": False,
                "employee_email": employee_email,
                "multiple_matches": bool(tracker_record.get("multiple_matches", False)),
                "matches": tracker_record.get("matches", []),
                "error": str(tracker_record.get("error", f"Tracker row not found for {employee_email}.")),
            }

        resolved_location = str(tracker_record.get("location", "") or work_location or "").strip()
        resolved_job_title = str(tracker_record.get("job_title", "") or job_title or "").strip()
        resolved_status_change = str(tracker_record.get("status_change", "") or status_change or "").strip()
        requested_start_date = str(tracker_record.get("start_date", "") or "").strip()
        employee_name = str(tracker_record.get("name", "") or employee_email).strip()
        resolved_submission_id = str(tracker_record.get("submission_id", "") or submission_id or "").strip()

        if not requested_start_date or not resolved_job_title or not resolved_location:
            return {
                "success": False,
                "employee_email": employee_email,
                "submission_id": resolved_submission_id,
                "error": "Tracker does not contain enough data to create the offer letter draft.",
            }

        client = _docusign()
        draft_result = await client.check_draft_exists(
            employee_email,
            resolved_location,
            resolved_job_title,
            resolved_status_change,
        )
        if not draft_result.get("exists"):
            draft_result = await client.create_envelope_draft(
                employee_name=employee_name,
                employee_email=employee_email,
                start_date=requested_start_date,
                position=resolved_job_title,
                work_location=resolved_location,
                status_change=resolved_status_change,
                submission_id=resolved_submission_id,
            )
            if not draft_result.get("success"):
                return {
                    "success": False,
                    "employee_email": employee_email,
                    "submission_id": resolved_submission_id,
                    "error": (
                        f"DocuSign draft creation failed for {employee_email}: "
                        f"{draft_result.get('error', 'unknown error')}"
                    ),
                }

        envelope_id = str(draft_result.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": employee_email,
                "submission_id": resolved_submission_id,
                "error": "DocuSign draft lookup succeeded but returned no envelope_id.",
            }

        review_result = await client.create_envelope_edit_view(envelope_id)
        review_url = str(review_result.get("url", "") or "").strip()
        return {
            "success": True,
            "employee_email": employee_email,
            "employee_name": employee_name,
            "submission_id": resolved_submission_id,
            "envelope_id": envelope_id,
            "status": "created",
            "start_date": requested_start_date,
            "work_location": resolved_location,
            "job_title": resolved_job_title,
            "status_change": resolved_status_change,
            "review_url": review_url,
            "summary": (
                "Offer letter draft created from the current tracker fields. "
                "Review the draft in DocuSign, then send it when ready."
            ),
        }

    @mcp.tool()
    async def send_docusign_envelope(envelope_id: str) -> dict[str, Any]:
        """Send an existing DocuSign draft envelope by envelope ID.

        Use this after `check_docusign_draft_exists` or
        `create_docusign_envelope_draft`. This tool sends the envelope but does
        not update tracker stages on its own.
        """
        client = _docusign()
        result = await client.send_envelope(envelope_id)
        return result

    @mcp.tool()
    async def list_docusign_drafts(
        employee_email: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        """List offer-letter drafts currently waiting to be sent.

        Use this for requests like "are there any drafts waiting?" or "show me
        drafts for this employee". Returns up to `limit` drafts and includes
        `total_count` so HR knows when more exist than are shown.
        """
        client = _docusign()
        result = await client.list_draft_envelopes(
            employee_email=employee_email,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
            limit=limit,
        )
        drafts = result.get("drafts", [])
        total_count = int(result.get("total_count", 0) or 0)
        if not drafts:
            result["summary"] = "No DocuSign drafts are currently waiting to be sent."
            return result

        preview = []
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            preview.append(
                {
                    "envelope_id": str(draft.get("envelope_id", "") or ""),
                    "employee_email": str(draft.get("employee_email", "") or ""),
                    "employee_name": str(draft.get("employee_name", "") or ""),
                    "work_location": str(draft.get("work_location", "") or ""),
                    "job_title": str(draft.get("job_title", "") or ""),
                    "status_change": str(draft.get("status_change", "") or ""),
                    "created_date_time": str(draft.get("created_date_time", "") or ""),
                }
            )
        result["drafts"] = preview
        result["summary"] = (
            f"Found {total_count} DocuSign draft(s) waiting to be sent."
            if total_count > len(preview)
            else f"Found {len(preview)} DocuSign draft(s) waiting to be sent."
        )
        return result

    @mcp.tool()
    async def delete_docusign_draft(
        envelope_id: str = "",
        employee_email: str = "",
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Delete one unsent DocuSign draft by envelope ID or tracker workflow.

        Prefer this for requests like "delete that draft" or "delete envelope
        123...". If `envelope_id` is provided, the tool deletes that specific
        draft directly. Otherwise it resolves the current tracker workflow first
        and deletes the matching unsent draft. Sent or completed envelopes are
        never deleted by this tool.
        """
        client = _docusign()
        if envelope_id.strip():
            return await client.delete_draft_envelope(envelope_id.strip())
        return await delete_offer_letter_draft_from_tracker(
            employee_email=employee_email,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )

    @mcp.tool()
    async def delete_offer_letter_draft_from_tracker(
        employee_email: str,
        work_location: str = "",
        job_title: str = "",
        status_change: str = "",
        submission_id: str = "",
    ) -> dict[str, Any]:
        """Delete the current unsent offer-letter draft for one tracker workflow.

        Prefer this for HR requests like "delete the draft" or "remove the
        offer letter draft". It resolves the current tracker row first,
        prefers `submission_id` when available, then finds the matching
        DocuSign envelope in `created` status and deletes it. This tool refuses
        sent or completed envelopes; only unsent drafts can be removed.
        """
        tracker_record = await _resolve_tracker_record_for_offer_letter(
            employee_email=employee_email,
            work_location=work_location,
            job_title=job_title,
            status_change=status_change,
            submission_id=submission_id,
        )
        if not tracker_record.get("found"):
            return {
                "success": False,
                "employee_email": employee_email,
                "multiple_matches": bool(tracker_record.get("multiple_matches", False)),
                "matches": tracker_record.get("matches", []),
                "error": str(tracker_record.get("error", f"Tracker row not found for {employee_email}.")),
            }

        resolved_location = str(tracker_record.get("location", "") or work_location or "").strip()
        resolved_job_title = str(tracker_record.get("job_title", "") or job_title or "").strip()
        resolved_status_change = str(tracker_record.get("status_change", "") or status_change or "").strip()
        resolved_submission_id = str(tracker_record.get("submission_id", "") or submission_id or "").strip()
        employee_name = str(tracker_record.get("name", "") or employee_email).strip()

        client = _docusign()
        draft_result = await client.check_draft_exists(
            employee_email,
            resolved_location,
            resolved_job_title,
            resolved_status_change,
        )
        if not draft_result.get("exists"):
            return {
                "success": False,
                "employee_email": employee_email,
                "employee_name": employee_name,
                "submission_id": resolved_submission_id,
                "work_location": resolved_location,
                "job_title": resolved_job_title,
                "status_change": resolved_status_change,
                "error": "No unsent offer letter draft exists for this workflow.",
            }

        envelope_id = str(draft_result.get("envelope_id", "") or "").strip()
        if not envelope_id:
            return {
                "success": False,
                "employee_email": employee_email,
                "employee_name": employee_name,
                "submission_id": resolved_submission_id,
                "work_location": resolved_location,
                "job_title": resolved_job_title,
                "status_change": resolved_status_change,
                "error": "DocuSign draft lookup succeeded but returned no envelope_id.",
            }

        delete_result = await client.delete_draft_envelope(envelope_id)
        if not delete_result.get("success"):
            return {
                "success": False,
                "employee_email": employee_email,
                "employee_name": employee_name,
                "submission_id": resolved_submission_id,
                "envelope_id": envelope_id,
                "work_location": resolved_location,
                "job_title": resolved_job_title,
                "status_change": resolved_status_change,
                "error": str(delete_result.get("error", "unknown error")),
            }

        return {
            "success": True,
            "employee_email": employee_email,
            "employee_name": employee_name,
            "submission_id": resolved_submission_id,
            "envelope_id": envelope_id,
            "status": "deleted",
            "work_location": resolved_location,
            "job_title": resolved_job_title,
            "status_change": resolved_status_change,
            "summary": "Offer letter draft deleted. A new draft can now be created from the current tracker fields.",
        }

    @mcp.tool()
    async def get_docusign_envelope_status(envelope_id: str) -> dict[str, Any]:
        """Retrieve the current DocuSign status and recipient tracking for an envelope."""
        client = _docusign()
        return await client.get_envelope_status(envelope_id)
