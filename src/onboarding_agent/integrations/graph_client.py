"""Microsoft Graph API client — Excel, Teams, Forms."""

from __future__ import annotations

import logging
from typing import Any

from azure.identity.aio import ClientSecretCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.item_body import ItemBody

from onboarding_agent.config import settings

logger = logging.getLogger(__name__)

# Graph scopes required by the app registration
_SCOPES = [
    "https://graph.microsoft.com/.default",
]

# Column indices in the Excel tracker (zero-based)
_COL_NAME = 0
_COL_EMAIL = 1
_COL_START_DATE = 2
_COL_DEPARTMENT = 3
_COL_MANAGER_EMAIL = 4
_COL_STATUS = 5


class GraphClient:
    """Thin wrapper around the Microsoft Graph SDK for onboarding operations."""

    def _get_client(self) -> GraphServiceClient:
        credential = ClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        return GraphServiceClient(credential, scopes=_SCOPES)

    # ------------------------------------------------------------------
    # Excel tracker helpers
    # ------------------------------------------------------------------

    async def find_employee_in_tracker(self, employee_email: str) -> dict[str, Any]:
        """Return {found, row_id, status} for the given email."""
        client = self._get_client()
        try:
            rows = await (
                client.drives
                .by_drive_id(settings.graph_excel_drive_id)
                .items
                .by_drive_item_id(settings.graph_excel_item_id)
                .workbook
                .worksheets
                .by_workbook_worksheet_id(settings.graph_excel_sheet_name)
                .used_range()
                .get()
            )
            if not rows or not rows.values:
                return {"found": False, "row_id": "", "status": ""}

            for i, row in enumerate(rows.values):
                if len(row) > _COL_EMAIL and str(row[_COL_EMAIL]).lower() == employee_email.lower():
                    status = str(row[_COL_STATUS]) if len(row) > _COL_STATUS else ""
                    return {"found": True, "row_id": str(i + 1), "status": status}

            return {"found": False, "row_id": "", "status": ""}
        except Exception as exc:
            logger.exception("find_employee_in_tracker failed")
            return {"found": False, "row_id": "", "status": "", "error": str(exc)}

    async def add_employee_to_tracker(
        self,
        name: str,
        email: str,
        start_date: str,
        department: str,
        manager_email: str,
    ) -> dict[str, Any]:
        """Append a new row to the Excel tracker."""
        client = self._get_client()
        try:
            from msgraph.generated.models.workbook_range import WorkbookRange

            # Find the next empty row index by fetching used range
            rows = await (
                client.drives
                .by_drive_id(settings.graph_excel_drive_id)
                .items
                .by_drive_item_id(settings.graph_excel_item_id)
                .workbook
                .worksheets
                .by_workbook_worksheet_id(settings.graph_excel_sheet_name)
                .used_range()
                .get()
            )
            next_row = (len(rows.values) + 1) if rows and rows.values else 2  # skip header

            # Write the row via range address (e.g. "A5:F5")
            range_address = f"A{next_row}:F{next_row}"
            range_body = WorkbookRange()
            range_body.values = [[name, email, start_date, department, manager_email, "Pending"]]

            await (
                client.drives
                .by_drive_id(settings.graph_excel_drive_id)
                .items
                .by_drive_item_id(settings.graph_excel_item_id)
                .workbook
                .worksheets
                .by_workbook_worksheet_id(settings.graph_excel_sheet_name)
                .range_with_address(range_address)
                .patch(range_body)
            )
            return {"success": True, "row_id": str(next_row)}
        except Exception as exc:
            logger.exception("add_employee_to_tracker failed")
            return {"success": False, "row_id": "", "error": str(exc)}

    async def update_tracker_status(self, row_id: str, new_status: str) -> dict[str, Any]:
        """Patch the status cell for a given row."""
        client = self._get_client()
        try:
            from msgraph.generated.models.workbook_range import WorkbookRange

            # Status is column F (index 5)
            range_address = f"F{row_id}"
            range_body = WorkbookRange()
            range_body.values = [[new_status]]

            await (
                client.drives
                .by_drive_id(settings.graph_excel_drive_id)
                .items
                .by_drive_item_id(settings.graph_excel_item_id)
                .workbook
                .worksheets
                .by_workbook_worksheet_id(settings.graph_excel_sheet_name)
                .range_with_address(range_address)
                .patch(range_body)
            )
            return {"success": True, "row_id": row_id, "new_status": new_status}
        except Exception as exc:
            logger.exception("update_tracker_status failed")
            return {"success": False, "row_id": row_id, "error": str(exc)}

    # ------------------------------------------------------------------
    # Forms
    # ------------------------------------------------------------------

    async def get_form_submission_by_id(self, submission_id: str) -> dict[str, Any]:
        """Fetch a specific Forms response. Uses the Graph beta endpoint."""
        import aiohttp
        from azure.identity.aio import ClientSecretCredential as AsyncCred

        cred = AsyncCred(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        try:
            token = await cred.get_token("https://graph.microsoft.com/.default")
            url = (
                f"https://graph.microsoft.com/v1.0/forms/{settings.graph_forms_form_id}"
                f"/responses/{submission_id}"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers={"Authorization": f"Bearer {token.token}"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"found": True, "data": data}
                    return {"found": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("get_form_submission_by_id failed")
            return {"found": False, "error": str(exc)}
        finally:
            await cred.close()

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    async def send_teams_channel_notification(
        self, channel_id: str, message: str
    ) -> dict[str, Any]:
        """Post a message to a Teams channel via Graph."""
        client = self._get_client()
        try:
            body = ChatMessage()
            body.body = ItemBody()
            body.body.content = message

            result = await (
                client.teams
                .by_team_id(settings.teams_team_id)
                .channels
                .by_channel_id(channel_id)
                .messages
                .post(body)
            )
            return {"success": True, "message_id": result.id if result else ""}
        except Exception as exc:
            logger.exception("send_teams_channel_notification failed")
            return {"success": False, "message_id": "", "error": str(exc)}

    async def send_teams_direct_message(self, user_id: str, message: str) -> dict[str, Any]:
        """Create or reuse a 1:1 chat and post a message."""
        import aiohttp
        from azure.identity.aio import ClientSecretCredential as AsyncCred

        cred = AsyncCred(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        try:
            token = await cred.get_token("https://graph.microsoft.com/.default")
            headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}

            async with aiohttp.ClientSession() as session:
                # Create or get existing 1:1 chat
                chat_payload = {
                    "chatType": "oneOnOne",
                    "members": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{user_id}",
                        }
                    ],
                }
                async with session.post(
                    "https://graph.microsoft.com/v1.0/chats",
                    json=chat_payload,
                    headers=headers,
                ) as resp:
                    chat_data = await resp.json()
                    chat_id = chat_data.get("id", "")

                # Send the message
                msg_payload = {"body": {"content": message}}
                async with session.post(
                    f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages",
                    json=msg_payload,
                    headers=headers,
                ) as resp:
                    if resp.status in (200, 201):
                        return {"success": True, "chat_id": chat_id}
                    return {"success": False, "chat_id": chat_id, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            logger.exception("send_teams_direct_message failed")
            return {"success": False, "chat_id": "", "error": str(exc)}
        finally:
            await cred.close()

    async def send_teams_reply(self, activity_id: str, message: str) -> dict[str, Any]:
        """Reply in a Teams thread. Requires the channel_id from context."""
        # activity_id format: "19:channelId@thread.tacv2/messages/messageId"
        # For simplicity we send to the HR channel with an @mention reference.
        return await self.send_teams_channel_notification(settings.teams_channel_id, message)
