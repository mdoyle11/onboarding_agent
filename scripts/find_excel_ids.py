#!/usr/bin/env python3
"""Utility for discovering Microsoft Graph drive IDs and workbook item IDs.

Examples:
    uv run python scripts/find_excel_ids.py list-drives
    uv run python scripts/find_excel_ids.py list-sites --search yourorg
    uv run python scripts/find_excel_ids.py list-site-drives --site-id contoso.sharepoint.com,site-id,web-id
    uv run python scripts/find_excel_ids.py list-items --drive-id b!abc123
    uv run python scripts/find_excel_ids.py search --drive-id b!abc123 --name roster
    uv run python scripts/find_excel_ids.py explore
    uv run python scripts/find_excel_ids.py explore-sites --search yourorg
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
from azure.identity.aio import ClientSecretCredential
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphDiscoverySettings(BaseSettings):
    """Minimal settings required for Graph discovery."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    graph_excel_drive_id: str = ""


class GraphDiscoveryClient:
    """Small Graph REST client for drive and file discovery."""

    def __init__(self, settings: GraphDiscoverySettings) -> None:
        self._settings = settings

    async def _token(self) -> str:
        credential = ClientSecretCredential(
            tenant_id=self._settings.azure_tenant_id,
            client_id=self._settings.azure_client_id,
            client_secret=self._settings.azure_client_secret,
        )
        try:
            token = await credential.get_token("https://graph.microsoft.com/.default")
            return token.token
        finally:
            await credential.close()

    async def _get(self, url: str) -> dict[str, Any]:
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session, session.get(url, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Graph request failed ({resp.status}): {text}")
            return {} if not text else await resp.json()

    async def _collect(self, url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_url = url
        while next_url:
            payload = await self._get(next_url)
            value = payload.get("value", [])
            if isinstance(value, list):
                results.extend(item for item in value if isinstance(item, dict))
            next_link = payload.get("@odata.nextLink")
            next_url = next_link if isinstance(next_link, str) and next_link else ""
        return results

    async def list_drives(self) -> list[dict[str, Any]]:
        return await self._collect("https://graph.microsoft.com/v1.0/drives")

    async def search_sites(self, query: str) -> list[dict[str, Any]]:
        encoded_query = quote(query)
        return await self._collect(f"https://graph.microsoft.com/v1.0/sites?search={encoded_query}")

    async def resolve_site_by_url(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        hostname = parsed.netloc.strip()
        site_path = parsed.path.strip("/")
        if not hostname or not site_path:
            raise ValueError("SharePoint site URL must include a hostname and site path, e.g. https://contoso.sharepoint.com/sites/HR")
        return await self._get(f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{site_path}")

    async def get_site(self, site_id: str) -> dict[str, Any]:
        return await self._get(f"https://graph.microsoft.com/v1.0/sites/{site_id}")

    async def list_site_drives(self, site_id: str) -> list[dict[str, Any]]:
        return await self._collect(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives")

    async def get_drive(self, drive_id: str) -> dict[str, Any]:
        return await self._get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}")

    async def list_items(self, drive_id: str, item_id: str = "", path: str = "") -> list[dict[str, Any]]:
        if path:
            encoded_path = quote(path.strip("/"))
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_path}:/children"
        elif item_id:
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children"
        else:
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        return await self._collect(url)

    async def search(self, drive_id: str, name: str) -> list[dict[str, Any]]:
        query = quote(name)
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/search(q='{query}')"
        return await self._collect(url)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-drives", help="List accessible drives.")
    subparsers.add_parser("explore", help="Open an interactive drive/folder explorer.")
    list_sites = subparsers.add_parser("list-sites", help="Search SharePoint sites by name.")
    list_sites.add_argument("--search", required=True, help="Free-text SharePoint site search term.")
    resolve_site_url = subparsers.add_parser("resolve-site-url", help="Resolve a SharePoint site URL to a Graph site ID.")
    resolve_site_url.add_argument("--url", required=True, help="SharePoint site URL, e.g. https://contoso.sharepoint.com/sites/HR")
    site_drives = subparsers.add_parser("list-site-drives", help="List drives/document libraries for a SharePoint site.")
    site_drives.add_argument("--site-id", required=True, help="Microsoft Graph site ID.")
    explore_sites = subparsers.add_parser("explore-sites", help="Interactively search sites and browse their drives.")
    explore_sites.add_argument("--search", default="", help="Optional initial SharePoint site search term.")
    explore_site_url = subparsers.add_parser("explore-site-url", help="Resolve a SharePoint site URL and browse its drives.")
    explore_site_url.add_argument("--url", required=True, help="SharePoint site URL, e.g. https://contoso.sharepoint.com/sites/HR")

    list_items = subparsers.add_parser("list-items", help="List children in a drive root, folder, or path.")
    list_items.add_argument("--drive-id", default="", help="Graph drive ID. Defaults to GRAPH_EXCEL_DRIVE_ID if set.")
    list_items.add_argument("--item-id", default="", help="Parent item/folder ID.")
    list_items.add_argument("--path", default="", help="Folder path from drive root, e.g. HR/Rosters.")

    search = subparsers.add_parser("search", help="Search a drive for files/folders by name.")
    search.add_argument("--drive-id", default="", help="Graph drive ID. Defaults to GRAPH_EXCEL_DRIVE_ID if set.")
    search.add_argument("--name", required=True, help="Substring to search for.")

    return parser


def _display(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No results found.")
        return

    for item in items:
        name = str(item.get("name", ""))
        item_id = str(item.get("id", ""))
        web_url = str(item.get("webUrl", ""))
        parent = item.get("parentReference", {}) if isinstance(item.get("parentReference"), dict) else {}
        drive_id = str(parent.get("driveId", ""))
        path = str(parent.get("path", ""))
        kind = "folder" if "folder" in item else "file"
        if "file" in item:
            mime = ((item.get("file") or {}) if isinstance(item.get("file"), dict) else {}).get("mimeType", "")
            if isinstance(mime, str) and "spreadsheet" in mime:
                kind = "excel"
        print(f"name: {name}")
        print(f"kind: {kind}")
        print(f"drive_id: {drive_id}")
        print(f"item_id: {item_id}")
        print(f"path: {path}")
        print(f"url: {web_url}")
        print("-" * 60)


def _display_sites(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No results found.")
        return

    for item in items:
        name = str(item.get("displayName", "") or item.get("name", ""))
        site_id = str(item.get("id", ""))
        web_url = str(item.get("webUrl", ""))
        site_collection = item.get("siteCollection", {}) if isinstance(item.get("siteCollection"), dict) else {}
        host = str(site_collection.get("hostname", ""))
        print(f"name: {name}")
        print("kind: site")
        print(f"site_id: {site_id}")
        print(f"hostname: {host}")
        print(f"url: {web_url}")
        print("-" * 60)


def _item_kind(item: dict[str, Any]) -> str:
    if "folder" in item:
        return "folder"
    if "file" in item:
        file_info = item.get("file")
        mime = file_info.get("mimeType", "") if isinstance(file_info, dict) else ""
        if isinstance(mime, str) and "spreadsheet" in mime:
            return "excel"
    return "file"


def _display_compact(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No results found.")
        return
    for index, item in enumerate(items, start=1):
        print(f"{index:>2}. [{_item_kind(item)}] {item.get('name', '')}")


def _display_sites_compact(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No results found.")
        return
    for index, item in enumerate(items, start=1):
        name = str(item.get("displayName", "") or item.get("name", ""))
        web_url = str(item.get("webUrl", ""))
        print(f"{index:>2}. [site] {name} :: {web_url}")


def _print_site_selection(item: dict[str, Any]) -> None:
    site_collection = item.get("siteCollection", {}) if isinstance(item.get("siteCollection"), dict) else {}
    print()
    print(f"name: {item.get('displayName', '') or item.get('name', '')}")
    print("kind: site")
    print(f"site_id: {item.get('id', '')}")
    print(f"hostname: {site_collection.get('hostname', '')}")
    print(f"url: {item.get('webUrl', '')}")
    print()


def _print_selection(item: dict[str, Any]) -> None:
    parent = item.get("parentReference", {}) if isinstance(item.get("parentReference"), dict) else {}
    print()
    print(f"name: {item.get('name', '')}")
    print(f"kind: {_item_kind(item)}")
    print(f"drive_id: {parent.get('driveId', '')}")
    print(f"item_id: {item.get('id', '')}")
    print(f"path: {parent.get('path', '')}")
    print(f"url: {item.get('webUrl', '')}")
    print()


async def _explore(client: GraphDiscoveryClient, settings: GraphDiscoverySettings) -> int:
    drives = await client.list_drives()
    if not drives:
        print("No drives found.")
        return 1

    while True:
        print("\nAvailable drives")
        _display_compact(drives)
        default_drive = settings.graph_excel_drive_id
        prompt = "Choose a drive number"
        if default_drive:
            prompt += ", press Enter for GRAPH_EXCEL_DRIVE_ID"
        prompt += ", or q to quit: "
        raw = input(prompt).strip().lower()
        if raw == "q":
            return 0

        selected_drive: dict[str, Any] | None = None
        if not raw and default_drive:
            for drive in drives:
                if str(drive.get("id", "")) == default_drive:
                    selected_drive = drive
                    break
            if selected_drive is None:
                try:
                    selected_drive = await client.get_drive(default_drive)
                except Exception as exc:
                    print(f"Could not load default drive: {exc}")
                    continue
        else:
            if not raw.isdigit():
                print("Please enter a drive number.")
                continue
            index = int(raw) - 1
            if index < 0 or index >= len(drives):
                print("Drive selection out of range.")
                continue
            selected_drive = drives[index]

        if selected_drive is None:
            print("Could not resolve drive selection.")
            continue
        result = await _explore_drive(client, selected_drive)
        if result == "quit":
            return 0


async def _explore_sites(client: GraphDiscoveryClient, initial_query: str) -> int:
    query = initial_query.strip()
    while True:
        if not query:
            query = input("SharePoint site search term (or q to quit): ").strip()
        if query.lower() == "q":
            return 0
        if not query:
            continue

        sites = await client.search_sites(query)
        if not sites:
            print(f"No sites found for {query!r}.")
            query = ""
            continue

        while True:
            print("\nMatching SharePoint sites")
            _display_sites_compact(sites)
            print()
            print("Commands:")
            print("  <number>  inspect site and choose one of its drives")
            print("  n         new site search")
            print("  q         quit")
            raw = input("> ").strip().lower()
            if raw == "q":
                return 0
            if raw == "n":
                query = ""
                break
            if not raw.isdigit():
                print("Unknown command.")
                continue
            index = int(raw) - 1
            if index < 0 or index >= len(sites):
                print("Selection out of range.")
                continue

            selected_site = sites[index]
            _print_site_selection(selected_site)
            site_id = str(selected_site.get("id", ""))
            drives = await client.list_site_drives(site_id)
            if not drives:
                print("No drives found for this site.")
                continue

            while True:
                print("Site drives")
                _display_compact(drives)
                print()
                print("Commands:")
                print("  <number>  explore drive")
                print("  b         back to sites")
                print("  q         quit")
                drive_raw = input("> ").strip().lower()
                if drive_raw == "q":
                    return 0
                if drive_raw == "b":
                    break
                if not drive_raw.isdigit():
                    print("Unknown command.")
                    continue
                drive_index = int(drive_raw) - 1
                if drive_index < 0 or drive_index >= len(drives):
                    print("Selection out of range.")
                    continue
                result = await _explore_drive(client, drives[drive_index])
                if result == "quit":
                    return 0


async def _explore_drive(client: GraphDiscoveryClient, drive: dict[str, Any]) -> str:
    drive_id = str(drive.get("id", ""))
    current_item_id = ""
    breadcrumb = "/"
    history: list[tuple[str, str]] = []

    while True:
        print()
        print(f"Drive: {drive.get('name', drive_id)}")
        print(f"Drive ID: {drive_id}")
        print(f"Folder: {breadcrumb}")
        print("-" * 60)
        items = await client.list_items(drive_id=drive_id, item_id=current_item_id)
        folders = [item for item in items if _item_kind(item) == "folder"]
        files = [item for item in items if _item_kind(item) != "folder"]
        ordered = folders + files
        _display_compact(ordered)
        print()
        print("Commands:")
        print("  <number>  open folder or inspect file")
        print("  s         search this drive by name")
        print("  p         print current folder info")
        print("  b         back one folder")
        print("  d         choose another drive")
        print("  q         quit")
        raw = input("> ").strip().lower()

        if raw == "q":
            return "quit"
        if raw == "d":
            return "drives"
        if raw == "p":
            print()
            print(f"drive_id: {drive_id}")
            print(f"item_id: {current_item_id or '<root>'}")
            print(f"path: {breadcrumb}")
            continue
        if raw == "b":
            if history:
                current_item_id, breadcrumb = history.pop()
            else:
                print("Already at the drive root.")
            continue
        if raw == "s":
            term = input("Search name: ").strip()
            if not term:
                continue
            matches = await client.search(drive_id=drive_id, name=term)
            print()
            print(f"Search results for {term!r}")
            _display_compact(matches)
            if not matches:
                continue
            choice = input("Select a result number to inspect, or press Enter to return: ").strip()
            if not choice:
                continue
            if not choice.isdigit():
                print("Invalid selection.")
                continue
            index = int(choice) - 1
            if index < 0 or index >= len(matches):
                print("Selection out of range.")
                continue
            _print_selection(matches[index])
            continue
        if not raw.isdigit():
            print("Unknown command.")
            continue

        index = int(raw) - 1
        if index < 0 or index >= len(ordered):
            print("Selection out of range.")
            continue
        selected = ordered[index]
        if _item_kind(selected) == "folder":
            history.append((current_item_id, breadcrumb))
            current_item_id = str(selected.get("id", ""))
            name = str(selected.get("name", "")).strip("/")
            breadcrumb = f"{breadcrumb.rstrip('/')}/{name}" if breadcrumb != "/" else f"/{name}"
            continue
        _print_selection(selected)


async def _run(args: argparse.Namespace) -> int:
    settings = GraphDiscoverySettings()
    if not settings.azure_tenant_id or not settings.azure_client_id or not settings.azure_client_secret:
        print("Missing Azure Graph credentials. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET.")
        return 2

    client = GraphDiscoveryClient(settings)

    if args.command == "list-drives":
        _display(await client.list_drives())
        return 0
    if args.command == "list-sites":
        _display_sites(await client.search_sites(args.search))
        return 0
    if args.command == "resolve-site-url":
        _print_site_selection(await client.resolve_site_by_url(args.url))
        return 0
    if args.command == "list-site-drives":
        _display(await client.list_site_drives(args.site_id))
        return 0
    if args.command == "explore":
        return await _explore(client, settings)
    if args.command == "explore-sites":
        return await _explore_sites(client, args.search)
    if args.command == "explore-site-url":
        site = await client.resolve_site_by_url(args.url)
        _print_site_selection(site)
        drives = await client.list_site_drives(str(site.get("id", "")))
        if not drives:
            print("No drives found for this site.")
            return 1
        while True:
            print("Site drives")
            _display_compact(drives)
            print()
            print("Commands:")
            print("  <number>  explore drive")
            print("  q         quit")
            raw = input("> ").strip().lower()
            if raw == "q":
                return 0
            if not raw.isdigit():
                print("Unknown command.")
                continue
            index = int(raw) - 1
            if index < 0 or index >= len(drives):
                print("Selection out of range.")
                continue
            result = await _explore_drive(client, drives[index])
            if result == "quit":
                return 0

    drive_id = args.drive_id or settings.graph_excel_drive_id
    if not drive_id:
        print("No drive ID provided. Use --drive-id or set GRAPH_EXCEL_DRIVE_ID.")
        return 2

    if args.command == "list-items":
        _display(await client.list_items(drive_id=drive_id, item_id=args.item_id, path=args.path))
        return 0

    if args.command == "search":
        _display(await client.search(drive_id=drive_id, name=args.name))
        return 0

    return 2


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
