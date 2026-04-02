"""Tests for tracker client table-backed read behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from onboarding_agent.integrations.workbook.schema import HEADER_ROW
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

_HEADER_INDEX = {header: idx for idx, header in enumerate(HEADER_ROW)}


def _build_row(values: dict[str, str]) -> list[str]:
    row = [""] * len(HEADER_ROW)
    for header, value in values.items():
        row[_HEADER_INDEX[header]] = value
    return row


@pytest.fixture(autouse=True)
def _reset_tracker_cache() -> None:
    TrackerClient._clear_index()


@pytest.mark.asyncio
async def test_find_employee_in_tracker_respects_table_start_row_offset():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Alice Example",
            "Staff Email": "alice@example.com",
            "Work Location": "Bronx",
            "Requested Start Date": "2026-04-01",
            "Job Title": "HR",
            "Requesting Manager": "manager@example.com",
            "Added to Tracker": "2026-03-31",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                return_value={
                    "address": "Onboarding!A5:P6",
                    "values": [HEADER_ROW, row],
                }
            ),
        ) as mock_request,
    ):
        result = await client.find_employee_in_tracker("alice@example.com")

    assert result["found"] is True
    assert result["row_id"] == "6"
    assert result["email"] == "alice@example.com"
    mock_request.assert_awaited_once()
    assert "/tables/OnboardingTable/range" in mock_request.await_args.args[1]


@pytest.mark.asyncio
async def test_find_employee_in_tracker_reuses_index_with_row_verification():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Alice Example",
            "Staff Email": "alice@example.com",
            "Job Title": "HR",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    {
                        "address": "Onboarding!A1:P2",
                        "values": [HEADER_ROW, row],
                    },
                    {
                        "address": "Onboarding!A2:P2",
                        "values": [row],
                    },
                ]
            ),
        ) as mock_request,
    ):
        first = await client.find_employee_in_tracker("alice@example.com")
        second = await client.find_employee_in_tracker("alice@example.com")

    assert first["found"] is True
    assert second["found"] is True
    # First call builds index from table range; second call verifies by direct row read.
    assert mock_request.await_count == 2
    assert "/worksheets/Onboarding/range" in mock_request.await_args_list[1].args[1]


@pytest.mark.asyncio
async def test_find_employee_in_tracker_falls_back_when_table_query_fails():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Bob Example",
            "Staff Email": "bob@example.com",
            "Added to Tracker": "2026-03-31",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    RuntimeError("table not found"),
                    {
                        "address": "Onboarding!A1:P2",
                        "values": [HEADER_ROW, row],
                    },
                ]
            ),
        ) as mock_request,
    ):
        result = await client.find_employee_in_tracker("bob@example.com")

    assert result["found"] is True
    assert result["row_id"] == "2"
    assert mock_request.await_count == 2


@pytest.mark.asyncio
async def test_add_employee_to_tracker_uses_table_rows_add_when_configured():
    client = TrackerClient()
    initial_row = _build_row(
        {
            "Staff Name": "Existing User",
            "Staff Email": "existing@example.com",
        }
    )

    added_row = _build_row(
        {
            "Staff Name": "New User",
            "Staff Email": "new@example.com",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    {"address": "Onboarding!A1:P2", "values": [HEADER_ROW, initial_row]},
                    {"index": 1},
                    {"address": "Onboarding!A1:P3", "values": [HEADER_ROW, initial_row, added_row]},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.add_employee_to_tracker(
            staff_name="New User",
            staff_email="new@example.com",
            requested_start_date="2026-04-01",
            job_title="HR",
            requesting_manager="manager@example.com",
            work_location="Bronx",
        )

    assert result["success"] is True
    assert result["row_id"] == "3"
    assert mock_request.await_args_list[1].args[0] == "POST"
    assert "/tables/OnboardingTable/rows/add" in mock_request.await_args_list[1].args[1]


@pytest.mark.asyncio
async def test_find_employee_in_tracker_requires_disambiguation_for_duplicate_email():
    client = TrackerClient()
    row1 = _build_row(
        {
            "Staff Name": "Alex Bronx",
            "Staff Email": "alex@example.com",
            "Work Location": "Bronx",
            "Job Title": "Teacher",
            "Added to Tracker": "2026-04-01",
        }
    )
    row2 = _build_row(
        {
            "Staff Name": "Alex Queens",
            "Staff Email": "alex@example.com",
            "Work Location": "Queens",
            "Job Title": "Teacher",
            "Added to Tracker": "2026-04-02",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                return_value={
                    "address": "Onboarding!A1:P3",
                    "values": [HEADER_ROW, row1, row2],
                }
            ),
        ),
    ):
        ambiguous = await client.find_employee_in_tracker("alex@example.com")
        disambiguated = await client.find_employee_in_tracker(
            "alex@example.com",
            location="Queens",
            job_title="Teacher",
        )

    assert ambiguous["found"] is False
    assert ambiguous["multiple_matches"] is True
    assert len(ambiguous["matches"]) == 2
    assert "added_to_tracker" in ambiguous["matches"][0]
    assert ambiguous["matches"][0]["added_to_tracker"] == "04/01/2026"
    assert ambiguous["matches"][1]["added_to_tracker"] == "04/02/2026"
    assert disambiguated["found"] is True
    assert disambiguated["location"] == "Queens"


@pytest.mark.asyncio
async def test_update_stage_refreshes_stage_columns_before_validation():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Alice Example",
            "Staff Email": "alice@example.com",
            "Work Location": "Bronx",
            "Job Title": "Teacher",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.update_stage(
            "alice@example.com",
            "Sent Offer Letter",
            location="Bronx",
            job_title="Teacher",
        )

    assert result["success"] is True
    assert mock_request.await_args_list[2].args[0] == "PATCH"
