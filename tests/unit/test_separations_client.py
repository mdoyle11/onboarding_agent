"""Tests for separations sheet field mapping."""

from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.integrations.workbook.separations_client import SeparationsClient


@pytest.mark.asyncio
async def test_add_separation_record_preserves_work_and_personal_email_columns() -> None:
    client = SeparationsClient()
    rows = [
        ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Location"],
    ]
    graph = AsyncMock(return_value={})

    with (
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "separations_sheet_name": "Separations",
            },
        ),
        patch.object(client, "_used_range_rows", new=AsyncMock(return_value=rows)),
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.add_separation_record(
            "alice@example.com",
            location="Bronx",
            status_change="Separation",
            roster_data={
                "employee_name": "Alice Example",
                "employee_email": "alice@company.org",
                "personal_email": "alice@example.com",
                "job_category": "Teacher",
                "position": "Teacher",
            },
        )

    assert result["success"] is True
    written_row = graph.await_args.args[2]["values"][0]
    assert written_row[0] == "Alice Example"
    assert written_row[1] == "alice@company.org"
    assert written_row[2] == "alice@example.com"


@pytest.mark.asyncio
async def test_add_separation_record_allows_same_email_for_different_role() -> None:
    client = SeparationsClient()
    rows = [
        ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Separation Type"],
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Separation"],
    ]
    graph = AsyncMock(return_value={})

    with (
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "separations_sheet_name": "Separations",
            },
        ),
        patch.object(client, "_used_range_rows", new=AsyncMock(return_value=rows)),
        patch.object(client, "_graph_workbook_request", new=graph),
    ):
        result = await client.add_separation_record(
            "alice@example.com",
            location="Bronx",
            status_change="Separation",
            job_title="Assistant Principal",
            job_category="Leadership",
            roster_data={
                "employee_name": "Alice Example",
                "employee_email": "alice@company.org",
                "personal_email": "alice@example.com",
                "job_category": "Leadership",
                "position": "Assistant Principal",
            },
        )

    assert result["success"] is True
    assert result.get("already_exists") is not True
    assert graph.await_count == 1


@pytest.mark.asyncio
async def test_add_separation_record_dedupes_same_email_same_role() -> None:
    client = SeparationsClient()
    rows = [
        ["Employee Name", "Employee Email", "Personal Email", "Group", "Position", "Separation Type"],
        ["Alice Example", "alice@company.org", "alice@example.com", "Teacher", "Teacher", "Separation"],
    ]

    with (
        patch.object(
            client,
            "_staff_roster_workbook",
            return_value={
                "drive_id": "drive-1",
                "item_id": "item-1",
                "separations_sheet_name": "Separations",
            },
        ),
        patch.object(client, "_used_range_rows", new=AsyncMock(return_value=rows)),
        patch.object(client, "_graph_workbook_request", new=AsyncMock()),
    ):
        result = await client.add_separation_record(
            "alice@example.com",
            location="Bronx",
            status_change="Separation",
            job_title="Teacher",
            job_category="Teacher",
            roster_data={
                "employee_name": "Alice Example",
                "employee_email": "alice@company.org",
                "personal_email": "alice@example.com",
                "job_category": "Teacher",
                "position": "Teacher",
            },
        )

    assert result["success"] is True
    assert result["already_exists"] is True
