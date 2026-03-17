#!/usr/bin/env python3
"""
Interactive step-by-step guide for Google Sheets tracker setup.

This script does NOT make API calls — it prints the exact steps to perform
in the Google Cloud Console and records the values you paste into .env.

Usage:
    python scripts/setup_google_sheets.py
"""

import json
import textwrap
import webbrowser


def step(n: int, title: str, body: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Step {n}: {title}")
    print(f"{'=' * 60}")
    print(textwrap.dedent(body).strip())


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"\n  Enter {label}{suffix}: ").strip()
    return value or default


def pause(instruction: str) -> None:
    input(f"\n  {instruction}\n  Press Enter when done...")


def open_url(url: str) -> None:
    print(f"\n  Opening: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        print("  (Could not open browser automatically — copy the URL above manually)")


def main() -> None:
    print("\n" + "=" * 60)
    print("  Google Sheets Tracker Setup Wizard")
    print("  Onboarding Agent — Tracker Backend")
    print("=" * 60)
    print("""
  This wizard walks you through:
    1. Creating a Google Cloud project
    2. Enabling the Google Sheets API
    3. Creating a service account (server-to-server auth — no user login needed)
    4. Downloading the service account JSON key
    5. Creating the onboarding tracker spreadsheet
    6. Sharing it with the service account
    7. Writing your .env values

  You need a Google account (any Gmail or Google Workspace account works).
""")

    # ------------------------------------------------------------------
    # Step 1 — Google Cloud project
    # ------------------------------------------------------------------
    step(1, "Create a Google Cloud project", """
  1. Go to: https://console.cloud.google.com/projectcreate
  2. Project name: OnboardingAgent
  3. Leave organisation as-is (or select your org if you have one)
  4. Click "Create"
  5. Wait ~10 seconds for it to provision, then make sure it is selected
     in the top project picker dropdown
""")
    open_url("https://console.cloud.google.com/projectcreate")
    pause("Create the project and select it in the top dropdown.")

    project_id = prompt("Your project ID (shown under the project name, e.g. onboardingagent-123456)")

    # ------------------------------------------------------------------
    # Step 2 — Enable the Sheets API
    # ------------------------------------------------------------------
    step(2, "Enable the Google Sheets API", """
  1. Go to: https://console.cloud.google.com/apis/library/sheets.googleapis.com
     (Make sure your new project is selected in the top dropdown)
  2. Click "Enable"
  3. Wait a few seconds for it to activate
""")
    open_url(
        f"https://console.cloud.google.com/apis/library/sheets.googleapis.com?project={project_id}"
    )
    pause("Enable the Google Sheets API.")

    # ------------------------------------------------------------------
    # Step 3 — Create a service account
    # ------------------------------------------------------------------
    step(3, "Create a service account", """
  A service account lets the agent authenticate to Google Sheets without
  any user having to log in — exactly like JWT Grant in DocuSign.

  1. Go to: https://console.cloud.google.com/iam-admin/serviceaccounts
  2. Click "+ Create Service Account"
  3. Service account name:   onboarding-agent
  4. Service account ID:     onboarding-agent  (auto-filled)
  5. Description:            Onboarding Agent tracker access
  6. Click "Create and Continue"
  7. On the "Grant this service account access" step — skip it (click Continue)
  8. On the "Grant users access" step — skip it (click Done)
  9. You will be taken back to the service accounts list
""")
    open_url(
        f"https://console.cloud.google.com/iam-admin/serviceaccounts?project={project_id}"
    )
    pause("Create the service account.")

    # ------------------------------------------------------------------
    # Step 4 — Download the JSON key
    # ------------------------------------------------------------------
    step(4, "Download the service account JSON key", """
  1. In the service accounts list, click the "onboarding-agent" account you just created
  2. Go to the "Keys" tab
  3. Click "Add Key" → "Create new key"
  4. Key type: JSON
  5. Click "Create" — a JSON file will download automatically
  6. Move it to your project directory and rename it:
       google_service_account.json
     (It is already in .gitignore as *.json if you add it — or add it manually)

  IMPORTANT: This file contains a private key. Never commit it to git.
  Add it to .gitignore:  echo "google_service_account.json" >> .gitignore
""")
    pause("Download the JSON key and move it to the project directory as google_service_account.json.")

    # Verify the file and extract the service account email
    service_account_email = ""
    key_path = "google_service_account.json"
    try:
        with open(key_path) as f:
            key_data = json.load(f)
        service_account_email = key_data.get("client_email", "")
        print(f"\n  ✓ Key file found. Service account email: {service_account_email}")
    except FileNotFoundError:
        service_account_email = prompt(
            "Service account email (from the JSON file, e.g. onboarding-agent@project.iam.gserviceaccount.com)"
        )
    except Exception as exc:
        print(f"\n  Warning: could not read key file — {exc}")
        service_account_email = prompt("Service account email")

    # ------------------------------------------------------------------
    # Step 5 — Create the Google Sheet
    # ------------------------------------------------------------------
    step(5, "Create the onboarding tracker spreadsheet", """
  1. Go to: https://sheets.new  (creates a blank spreadsheet)
  2. Rename it: click "Untitled spreadsheet" at the top → type "OnboardingTracker"
  3. Rename the tab at the bottom: double-click "Sheet1" → type "Onboarding"
  4. Add this header row in row 1 (one value per cell, A through F):
       A1: Name
       B1: Email
       C1: StartDate
       D1: Department
       E1: ManagerEmail
       F1: Status
  5. Bold the header row (optional but recommended)
  6. Copy the Spreadsheet ID from the URL:
       https://docs.google.com/spreadsheets/d/  <<<THIS PART>>>  /edit
""")
    open_url("https://sheets.new")
    pause("Create the spreadsheet with the header row.")

    sheets_id = prompt("Spreadsheet ID (from the URL)")

    # ------------------------------------------------------------------
    # Step 6 — Share with service account
    # ------------------------------------------------------------------
    step(6, "Share the spreadsheet with the service account", f"""
  The agent authenticates as the service account, so the spreadsheet
  must be shared with it — just like sharing with a colleague.

  1. In the Google Sheet, click the "Share" button (top right)
  2. In the "Add people and groups" field, paste this email:
       {service_account_email}
  3. Set the permission to "Editor"
  4. Uncheck "Notify people" (the service account has no inbox)
  5. Click "Share"
""")
    pause(f"Share the spreadsheet with {service_account_email or 'the service account email'}.")

    # ------------------------------------------------------------------
    # Write .env snippet
    # ------------------------------------------------------------------
    env_content = f"""# Generated by setup_google_sheets.py
TRACKER_BACKEND=sheets
GOOGLE_SERVICE_ACCOUNT_PATH=./google_service_account.json
GOOGLE_SHEETS_ID={sheets_id}
GOOGLE_SHEETS_TAB=Onboarding
"""

    out_file = ".env.sheets"
    with open(out_file, "w") as f:
        f.write(env_content)

    print(f"\n{'=' * 60}")
    print("  All done!")
    print(f"{'=' * 60}")
    print(f"""
  Values written to: {out_file}

  Merge these into your .env file:

    TRACKER_BACKEND=sheets
    GOOGLE_SERVICE_ACCOUNT_PATH=./google_service_account.json
    GOOGLE_SHEETS_ID={sheets_id}
    GOOGLE_SHEETS_TAB=Onboarding

  Also add the key file to .gitignore:
    echo "google_service_account.json" >> .gitignore

  To verify the connection, start the server and POST a curl webhook:
    python -m onboarding_agent.server

  Then in another terminal:
    curl -X POST http://localhost:8080/webhook/new-hire \\
      -H "Content-Type: application/json" \\
      -H "X-Webhook-Secret: your-webhook-secret" \\
      -d '{{
        "employeeName": "Test User",
        "employeeEmail": "test@example.com",
        "startDate": "2026-04-14",
        "department": "Engineering",
        "managerEmail": "manager@example.com",
        "submissionId": "test-001"
      }}'

  A new row should appear in your Google Sheet within ~15 seconds.
""")


if __name__ == "__main__":
    main()
