#!/usr/bin/env python3
"""One-time script to generate a Gmail OAuth2 refresh token.

Prerequisites:
  1. Go to Google Cloud Console → APIs & Services → Library → enable "Gmail API"
  2. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID
     - Application type: Desktop app
     - Download the JSON file

Usage:
  python scripts/generate_gmail_token.py path/to/client_secret.json

The script opens a browser for you to consent, then prints the refresh token
and client credentials to add to your .env file.
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_gmail_token.py <client_secret.json>")
        sys.exit(1)

    client_secret_path = sys.argv[1]

    with open(client_secret_path) as f:
        client_config = json.load(f)

    # Extract client ID and secret for .env output
    installed = client_config.get("installed", client_config.get("web", {}))
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes=_SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("Add these to your .env file:")
    print("=" * 60)
    print(f"GMAIL_SENDER_EMAIL={creds.token_uri}")  # placeholder — user fills in
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)
    print("\nRemember to set GMAIL_SENDER_EMAIL to your actual Gmail address.")


if __name__ == "__main__":
    main()
