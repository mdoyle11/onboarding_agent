#!/usr/bin/env python3
"""
Interactive step-by-step guide for DocuSign JWT Grant (JWA) setup.

Covers:
  - Creating a DocuSign developer account
  - Generating an RSA key pair
  - Creating an Integration Key and uploading the public key
  - Granting user consent (one-time)
  - Creating an envelope template with a signer role
  - Writing .env values

Usage:
    python scripts/setup_docusign.py
"""

import json
import textwrap
import webbrowser
from pathlib import Path


PRIVATE_KEY_FILE = Path("docusign_private.key")
PUBLIC_KEY_FILE = Path("docusign_public.pem")

DEMO_ADMIN_URL = "https://admindemo.docusign.com"
DEMO_AUTH_URL = "https://account-d.docusign.com"


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


def generate_keys() -> None:
    """Generate RSA key pair using the existing script logic."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if PRIVATE_KEY_FILE.exists():
        print(f"\n  ✓ {PRIVATE_KEY_FILE} already exists — skipping key generation")
        return

    print("\n  Generating 2048-bit RSA key pair...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    PRIVATE_KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PRIVATE_KEY_FILE.chmod(0o600)

    PUBLIC_KEY_FILE.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"  ✓ Private key → {PRIVATE_KEY_FILE}  (mode 600, never commit this)")
    print(f"  ✓ Public key  → {PUBLIC_KEY_FILE}  (safe to share with DocuSign)")


def main() -> None:
    print("\n" + "=" * 60)
    print("  DocuSign JWT Grant (JWA) Setup Wizard")
    print("  Onboarding Agent — Document Signing")
    print("=" * 60)
    print("""
  JWT Grant (also called JWA — JSON Web Authentication) lets the agent
  sign documents on behalf of a user without any interactive login.
  The agent generates a signed JWT, exchanges it for an access token,
  and calls the DocuSign API — fully unattended.

  This wizard covers:
    1. Creating a free DocuSign developer account
    2. Generating your RSA key pair
    3. Creating an Integration Key and uploading the public key
    4. Granting user consent (one-time browser step)
    5. Creating an envelope template
    6. Collecting your Account ID and User ID
""")

    # ------------------------------------------------------------------
    # Step 1 — Developer account
    # ------------------------------------------------------------------
    step(1, "Create a free DocuSign developer account", """
  If you already have a DocuSign developer account, skip to step 2.

  1. Go to: https://developers.docusign.com
  2. Click "Create a Free Account" (top right)
  3. Fill in your details and verify your email
  4. You will land on the DocuSign developer dashboard

  NOTE: This is a sandbox account — no real documents are signed.
  Production setup follows the same steps on account.docusign.com.
""")
    open_url("https://developers.docusign.com")
    pause("Create your developer account and log in to the dashboard.")

    # ------------------------------------------------------------------
    # Step 2 — RSA key pair
    # ------------------------------------------------------------------
    step(2, "Generate your RSA key pair", """
  The agent will sign JWTs with the private key.
  DocuSign will verify them with the public key you upload in step 3.

  Generating keys now...
""")
    try:
        generate_keys()
    except ImportError:
        print("""
  Could not auto-generate keys — cryptography package not installed yet.
  Run this after installing dependencies:
      uv pip install cryptography
      python scripts/generate_docusign_keys.py
  Then re-run this wizard.
""")
        return

    public_key_contents = PUBLIC_KEY_FILE.read_text()
    print(f"\n  Your public key (you will paste this into DocuSign in step 3):\n")
    print(public_key_contents)

    # ------------------------------------------------------------------
    # Step 3 — Integration Key
    # ------------------------------------------------------------------
    step(3, "Create an Integration Key and upload your public key", """
  1. Go to: https://admindemo.docusign.com
  2. Log in with your developer account
  3. In the left sidebar click "Apps and Keys"
     (or go to Settings → Apps and Keys)
  4. Click "+ Add App and Integration Key"
  5. App name: OnboardingAgent
  6. Click "Create App"
  7. You will see your Integration Key (a UUID) — copy it
  8. Scroll down to "Authentication" → "Service Integration"
  9. Under "RSA Keypairs" click "Add RSA Key"
  10. Paste the ENTIRE contents of docusign_public.pem into the box
      (including the -----BEGIN PUBLIC KEY----- and -----END PUBLIC KEY----- lines)
  11. Click "Add"
  12. Click "Save" at the bottom of the page
""")
    open_url(f"{DEMO_ADMIN_URL}/apps-and-keys")
    pause("Create the Integration Key and upload the public key.")

    integration_key = prompt("Integration Key (UUID from Apps and Keys page)")

    # ------------------------------------------------------------------
    # Step 4 — User ID and Account ID
    # ------------------------------------------------------------------
    step(4, "Get your User ID and Account ID", """
  1. In the DocuSign admin dashboard, click your name/avatar (top right)
  2. Click "My Preferences" (or "Profile")
  3. Your User ID (API Username) is shown on this page — copy it

  For Account ID:
  4. Click your name/avatar again → "Manage Account"
     OR go to: https://admindemo.docusign.com/api-account-id
  5. Your Account ID (API Account ID) is shown — copy it

  Both are UUIDs in the format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
""")
    open_url(f"{DEMO_ADMIN_URL}/api-account-id")
    pause("Copy your User ID and Account ID.")

    user_id = prompt("User ID (API Username UUID)")
    account_id = prompt("Account ID (API Account ID UUID)")

    # ------------------------------------------------------------------
    # Step 5 — User consent (one-time)
    # ------------------------------------------------------------------
    step(5, "Grant user consent (one-time browser step)", f"""
  JWT Grant requires the user to consent to impersonation once.
  After this, the agent can get tokens silently forever.

  1. Open this URL in your browser (replace YOUR_INTEGRATION_KEY):

  {DEMO_AUTH_URL}/oauth/auth?response_type=code&scope=signature%20impersonation&client_id={integration_key or 'YOUR_INTEGRATION_KEY'}&redirect_uri=https://www.docusign.com

  2. Log in with your DocuSign developer account if prompted
  3. Click "Accept" on the permissions screen
  4. You will be redirected to www.docusign.com — that is expected and correct

  You only need to do this once. The agent will handle token refresh automatically.
""")
    consent_url = (
        f"{DEMO_AUTH_URL}/oauth/auth"
        f"?response_type=code"
        f"&scope=signature%20impersonation"
        f"&client_id={integration_key or 'YOUR_INTEGRATION_KEY'}"
        f"&redirect_uri=https://www.docusign.com"
    )
    open_url(consent_url)
    pause("Grant consent in the browser, then come back here.")

    # ------------------------------------------------------------------
    # Step 6 — Envelope template
    # ------------------------------------------------------------------
    step(6, "Create an envelope template", """
  The agent creates envelopes from a pre-built template, which defines
  the document, signing fields, and recipient roles.

  1. In the DocuSign dashboard, click "Templates" in the top navigation
  2. Click "New" → "Create Template"
  3. Template name: Onboarding Agreement
  4. Upload a PDF document (any PDF works for testing — e.g. a blank one)
  5. Click "Next"

  Add a recipient role:
  6. Under "Add Recipients", set:
       Role:  signer          ← must be exactly this (lowercase)
       Name:  (leave blank — filled at send time)
       Email: (leave blank — filled at send time)
  7. Click "Next"

  Add text fields (optional but enables start date / department pre-fill):
  8. Drag a "Text" field onto the document
  9. In the field properties panel, set the "Data Label" to:  StartDate
  10. Drag another "Text" field and set its "Data Label" to:  Department
  11. Add a Signature field for the signer role

  Save the template:
  12. Click "Save and Close"
  13. Back in the Templates list, click on your new template
  14. Copy the Template ID from the URL:
        https://app.docusign.com/templates/  <<<THIS PART>>>  /recipients
""")
    open_url(f"{DEMO_ADMIN_URL}/home")
    pause("Create the template and copy the Template ID from the URL.")

    template_id = prompt("Template ID (UUID from the template URL)")

    # ------------------------------------------------------------------
    # Write .env snippet
    # ------------------------------------------------------------------
    env_content = f"""# Generated by setup_docusign.py
DOCUSIGN_ACCOUNT_ID={account_id}
DOCUSIGN_INTEGRATION_KEY={integration_key}
DOCUSIGN_USER_ID={user_id}
DOCUSIGN_PRIVATE_KEY_PATH=./{PRIVATE_KEY_FILE}
DOCUSIGN_TEMPLATE_ID={template_id}
DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi
"""

    out_file = ".env.docusign"
    with open(out_file, "w") as f:
        f.write(env_content)

    print(f"\n{'=' * 60}")
    print("  All done!")
    print(f"{'=' * 60}")
    print(f"""
  Values written to: {out_file}

  Merge these into your .env file:

    DOCUSIGN_ACCOUNT_ID={account_id}
    DOCUSIGN_INTEGRATION_KEY={integration_key}
    DOCUSIGN_USER_ID={user_id}
    DOCUSIGN_PRIVATE_KEY_PATH=./{PRIVATE_KEY_FILE}
    DOCUSIGN_TEMPLATE_ID={template_id}
    DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi

  Files created:
    {PRIVATE_KEY_FILE}  ← private key (gitignored, never commit)
    {PUBLIC_KEY_FILE}   ← public key (already uploaded to DocuSign)

  To verify the JWT auth works, start the server and send a test webhook:
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

  A DocuSign draft envelope should appear in your sandbox dashboard
  under Manage → Drafts within ~15 seconds.

  When you are ready for production:
    - Change DOCUSIGN_BASE_URL to: https://www.docusign.net/restapi
    - Repeat steps 3-5 on account.docusign.com with a production account
""")


if __name__ == "__main__":
    main()
