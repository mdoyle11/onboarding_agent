"""Tests for tracker client table-backed read behavior."""

from unittest.mock import AsyncMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from onboarding_agent.integrations.workbook.schema import HEADER_ROW
from onboarding_agent.integrations.workbook.tracker_client import TrackerClient

_HEADER_INDEX = {header: idx for idx, header in enumerate(HEADER_ROW)}


def _build_row(values: dict[str, str]) -> list[str]:
    row = [""] * len(HEADER_ROW)
    for header, value in values.items():
        row[_HEADER_INDEX[header]] = value
    return row


@pytest.fixture()
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    original_provider = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = original_provider  # type: ignore[attr-defined]


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
async def test_find_employee_in_tracker_prefers_submission_id_when_present():
    client = TrackerClient()
    header = ["Submission ID", *HEADER_ROW]
    base_row = _build_row(
        {
            "Staff Name": "Alice Example",
            "Staff Email": "alice@example.com",
            "Work Location": "Bronx",
            "Job Title": "Teacher",
            "Status Change": "Promotion",
        }
    )
    row = ["sub-123", *base_row]

    with patch.object(
        client,
        "_graph_workbook_request",
        AsyncMock(
            return_value={
                "address": "Onboarding!A1:Q2",
                "values": [header, row],
            }
        ),
    ):
        result = await client.find_employee_in_tracker(
            "alice@example.com",
            submission_id="sub-123",
        )

    assert result["found"] is True
    assert result["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_find_employee_in_tracker_uses_submission_id_before_cached_duplicate_email_matches():
    client = TrackerClient()
    header = ["Submission ID", *HEADER_ROW]
    base_row1 = _build_row(
        {
            "Staff Name": "Matt One",
            "Staff Email": "matt@example.com",
            "Work Location": "Collier",
            "Job Title": "Counselor",
            "Status Change": "New Hire",
        }
    )
    base_row2 = _build_row(
        {
            "Staff Name": "Matt Two",
            "Staff Email": "matt@example.com",
            "Work Location": "Orange",
            "Job Title": "Assistant Principal",
            "Status Change": "New Hire",
        }
    )
    row1 = ["sub-111", *base_row1]
    row2 = ["sub-222", *base_row2]

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    {"address": "Onboarding!A1:Q3", "values": [header, row1, row2]},
                    {"address": "Onboarding!A1:Q3", "values": [header, row1, row2]},
                ]
            ),
        ),
    ):
        ambiguous = await client.find_employee_in_tracker("matt@example.com")
        resolved = await client.find_employee_in_tracker(
            "matt@example.com",
            submission_id="sub-222",
        )

    assert ambiguous["found"] is False
    assert ambiguous["multiple_matches"] is True
    assert resolved["found"] is True
    assert resolved["submission_id"] == "sub-222"
    assert resolved["location"] == "Orange"


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
    assert mock_request.await_args_list[-1].args[0] == "PATCH"


@pytest.mark.asyncio
async def test_update_stage_relaxes_stale_identity_filters_for_unique_email_match():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Nancy Cruz",
            "Staff Email": "alice@example.com",
            "Work Location": "Collier",
            "Job Title": "Teacher",
            "Status Change": "New Hire",
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
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.update_stage(
            "alice@example.com",
            "Background Submission",
            location="Collier",
            job_title="Wrong Title",
            status_change="Leave Start",
        )

    assert result["success"] is True
    assert mock_request.await_args_list[-1].args[0] == "PATCH"


@pytest.mark.asyncio
async def test_update_stage_emits_tracker_latency_spans(span_exporter):
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Nancy Cruz",
            "Staff Email": "alice@example.com",
            "Work Location": "Collier",
            "Job Title": "Teacher",
            "Status Change": "New Hire",
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
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, row]},
                    {},
                ]
            ),
        ),
    ):
        result = await client.update_stage(
            "alice@example.com",
            "Background Submission",
            location="Collier",
            job_title="Wrong Title",
            status_change="Leave Start",
        )

    assert result["success"] is True
    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert "tracker.update_stage" in spans
    assert "tracker.resolve_stage" in spans
    assert "tracker.resolve_employee_for_stage_update" in spans
    assert "graph.excel.tracker.update_stage_cell" in spans
    update_attrs = spans["tracker.update_stage"].attributes
    assert update_attrs["tracker.lookup.result"] == "found"
    assert update_attrs["tracker.write_performed"] is True
    assert update_attrs["onboarding.lookup.result"] == "found"
    assert update_attrs["onboarding.write_performed"] is True
    assert update_attrs["onboarding.needs_clarification"] is False
    assert update_attrs["onboarding.stage.resolved"] == "Background Submission"
    assert update_attrs["employee.email_hash"]
    assert "alice" not in str(update_attrs)


@pytest.mark.asyncio
async def test_update_stage_surfaces_ambiguity_for_duplicate_email_matches():
    client = TrackerClient()
    row1 = _build_row(
        {
            "Staff Name": "Nancy Cruz",
            "Staff Email": "alice@example.com",
            "Work Location": "Collier",
            "Job Title": "Teacher",
            "Status Change": "New Hire",
            "Added to Tracker": "2026-04-01",
        }
    )
    row2 = _build_row(
        {
            "Staff Name": "Nancy Cruz",
            "Staff Email": "alice@example.com",
            "Work Location": "Collier",
            "Job Title": "Coach",
            "Status Change": "Transfer In",
            "Added to Tracker": "2026-04-02",
        }
    )

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(return_value={"address": "Onboarding!A1:AA3", "values": [HEADER_ROW, row1, row2]}),
        ) as mock_request,
    ):
        result = await client.update_stage(
            "alice@example.com",
            "Background Submission",
            location="Wrong Location",
            job_title="Wrong Title",
            status_change="Leave Start",
        )

    assert result["success"] is False
    assert result["multiple_matches"] is True
    assert len(result["matches"]) == 2
    assert "Multiple tracker rows" in result["error"]
    assert all(call.args[0] == "GET" for call in mock_request.await_args_list)


@pytest.mark.asyncio
async def test_update_stage_accepts_legacy_completed_in_adp_header_alias():
    client = TrackerClient()
    legacy_header = [header if header != "Complete in ADP" else "Completed in ADP" for header in HEADER_ROW]
    row = [""] * len(legacy_header)
    row[legacy_header.index("Staff Name")] = "Alice Example"
    row[legacy_header.index("Staff Email")] = "alice@example.com"
    row[legacy_header.index("Work Location")] = "Bronx"
    row[legacy_header.index("Job Title")] = "Teacher"

    with (
        patch("onboarding_agent.integrations.workbook.tracker_client.settings.graph_excel_table_name", "OnboardingTable"),
        patch.object(
            client,
            "_graph_workbook_request",
            AsyncMock(
                side_effect=[
                    {"address": "Onboarding!A1:AA2", "values": [legacy_header, row]},
                    {"address": "Onboarding!A1:AA2", "values": [legacy_header, row]},
                    {},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.update_stage(
            "alice@example.com",
            "Complete in ADP",
            location="Bronx",
            job_title="Teacher",
        )

    assert result["success"] is True
    assert mock_request.await_args_list[2].args[0] == "PATCH"


@pytest.mark.asyncio
async def test_remove_employee_from_tracker_deletes_row_and_verifies():
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
                    {"address": "Onboarding!A1:P2", "values": [HEADER_ROW, row]},
                    {"address": "Onboarding!A2:P2", "values": [row]},
                    {},
                    {"address": "Onboarding!A1:P1", "values": [HEADER_ROW]},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.remove_employee_from_tracker(
            "alice@example.com",
            location="Bronx",
            job_title="Teacher",
        )

    assert result["success"] is True
    assert mock_request.await_args_list[2].args[0] == "POST"
    assert "/range(address='A2%3AAA2')/delete" in mock_request.await_args_list[2].args[1]


@pytest.mark.asyncio
async def test_update_employee_in_tracker_patches_row_and_verifies():
    client = TrackerClient()
    row = _build_row(
        {
            "Staff Name": "Alice Example",
            "Staff Email": "alice@example.com",
            "Work Location": "Bronx",
            "Requested Start Date": "2026-04-01",
            "Job Title": "Teacher",
            "Status Change": "New Hire",
        }
    )
    updated_row = _build_row(
        {
            "Staff Name": "Alice Smith",
            "Staff Email": "alice@example.com",
            "Work Location": "Queens",
            "Requested Start Date": "2026-04-15",
            "Job Title": "Assistant Principal",
            "Status Change": "Promotion",
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
                    {"address": "Onboarding!A2:AA2", "values": [row]},
                    {},
                    {"address": "Onboarding!A1:AA2", "values": [HEADER_ROW, updated_row]},
                ]
            ),
        ) as mock_request,
    ):
        result = await client.update_employee_in_tracker(
            "alice@example.com",
            location="Bronx",
            current_job_title="Teacher",
            current_status_change="New Hire",
            staff_name="Alice Smith",
            requested_start_date="2026-04-15",
            work_location="Queens",
            job_title="Assistant Principal",
            status_change="Promotion",
        )

    assert result["success"] is True
    assert result["row_id"] == "2"
    assert result["updated_fields"] == [
        "job_title",
        "requested_start_date",
        "staff_name",
        "status_change",
        "work_location",
    ]
    assert mock_request.await_args_list[2].args[0] == "PATCH"
    assert "/range(address='A2%3AAA2')" in mock_request.await_args_list[2].args[1]
