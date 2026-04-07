"""Shared Graph workbook client behavior."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote

import aiohttp

from onboarding_agent.config import settings
from onboarding_agent.integrations.graph.auth import graph_access_token

logger = logging.getLogger(__name__)

_ADDRESS_ROW_RE = re.compile(r"[A-Z]+(\d+)")


class WorkbookGraphClient:
    """Shared Graph workbook operations for tracker and roster clients."""

    @staticmethod
    def _start_row_from_address(address: str) -> int:
        if not address:
            return 1
        match = _ADDRESS_ROW_RE.search(address.split("!", 1)[-1])
        if match is None:
            return 1
        try:
            return int(match.group(1))
        except ValueError:
            return 1

    async def _tracker_rows_with_start_row(self) -> tuple[int, list[list[Any]]]:
        """Return tracker rows and the worksheet row number of the header row."""
        table_name = settings.graph_excel_table_name.strip()
        if table_name:
            try:
                table_data = await self._graph_workbook_request(
                    "GET",
                    f"/tables/{quote(table_name)}/range",
                )
                table_values = table_data.get("values", []) if isinstance(table_data, dict) else []
                if table_values:
                    return (
                        self._start_row_from_address(str(table_data.get("address", "") or "")),
                        cast(list[list[Any]], table_values),
                    )
            except Exception:
                logger.warning(
                    "Falling back to usedRange for tracker reads; table '%s' query failed",
                    table_name,
                    exc_info=True,
                )

        used_range_data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(settings.graph_excel_sheet_name)}/usedRange(valuesOnly=true)",
        )
        used_range_values = used_range_data.get("values", []) if isinstance(used_range_data, dict) else []
        if not used_range_values:
            return 1, []
        return (
            self._start_row_from_address(str(used_range_data.get("address", "") or "")),
            cast(list[list[Any]], used_range_values),
        )

    async def _used_range_rows(
        self,
        *,
        drive_id: str | None = None,
        item_id: str | None = None,
        sheet_name: str | None = None,
    ) -> list[list[Any]]:
        if drive_id is None and item_id is None and sheet_name is None:
            _, rows = await self._tracker_rows_with_start_row()
            return rows

        data = await self._graph_workbook_request(
            "GET",
            f"/worksheets/{quote(sheet_name or settings.graph_excel_sheet_name)}/usedRange(valuesOnly=true)",
            drive_id=drive_id,
            item_id=item_id,
        )
        values = data.get("values", []) if isinstance(data, dict) else []
        if not values:
            return []
        return cast(list[list[Any]], values)

    async def _graph_access_token(self) -> str:
        return await graph_access_token()

    async def _graph_workbook_request(
        self,
        method: str,
        workbook_path: str,
        json_body: dict[str, Any] | None = None,
        *,
        drive_id: str | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        token = await self._graph_access_token()
        url = (
            "https://graph.microsoft.com/v1.0"
            f"/drives/{drive_id or settings.graph_excel_drive_id}"
            f"/items/{item_id or settings.graph_excel_item_id}"
            f"/workbook{workbook_path}"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with (
            aiohttp.ClientSession() as session,
            session.request(method, url, headers=headers, json=json_body) as resp,
        ):
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"Graph workbook request failed ({resp.status}): {body}")
            if resp.content_length == 0:
                logger.info(
                    "Graph workbook request %s %s completed in %.3fs",
                    method,
                    workbook_path,
                    perf_counter() - started,
                )
                return {}
            text = await resp.text()
            result = {} if not text else await resp.json()
            logger.info(
                "Graph workbook request %s %s completed in %.3fs",
                method,
                workbook_path,
                perf_counter() - started,
            )
            return result

    def _staff_roster_workbook(self, location: str) -> dict[str, str]:
        workbook = settings.staff_roster_workbook(location)
        if workbook is None:
            raise ValueError(f"No staff roster workbook configured for location '{location}'")
        if not workbook.get("drive_id") or not workbook.get("item_id"):
            raise ValueError(f"Staff roster workbook for '{location}' is missing drive_id or item_id")
        return workbook
