#!/usr/bin/env python3
"""
Interactive step-by-step guide for Slack workspace + app setup.

This script does NOT make API calls — it prints the exact steps to perform
in the Slack web UI and records the values you paste into .env.

Usage:
    python scripts/setup_slack.py
"""

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
    print("  Slack Workspace + App Setup Wizard")
    print("  Onboarding Agent — HR Chat Interface")
    print("=" * 60)
    print("""
  This wizard walks you through:
    1. Creating a free Slack workspace (if you don't have one)
    2. Creating a Slack app with the right permissions
    3. Enabling Socket Mode (no public URL needed)
    4. Getting your bot and app tokens
    5. Writing your .env values
""")

    # ------------------------------------------------------------------
    # Step 1 — Workspace
    # ------------------------------------------------------------------
    step(1, "Create a free Slack workspace", """
  If you already have a Slack workspace you can use, skip to step 2.

  1. Go to: https://slack.com/get-started#/createnew
  2. Enter your email address and click Continue
  3. Enter the confirmation code sent to your email
  4. When asked "What's the name of your company or team?", enter something
     like:  YourCompany HR  (this becomes your workspace name)
  5. Skip or complete the "Who are you working with?" step
  6. You now have a free Slack workspace — you are the admin
""")
    open_url("https://slack.com/get-started#/createnew")
    pause("Complete workspace creation, then come back here.")

    workspace_name = prompt("Your workspace name (e.g. yourcompany)")
    workspace_url = f"https://{workspace_name.lower().replace(' ', '-')}.slack.com"
    print(f"\n  Your workspace URL should be: {workspace_url}")

    # ------------------------------------------------------------------
    # Step 2 — Create a Slack app
    # ------------------------------------------------------------------
    step(2, "Create a Slack app", """
  1. Go to: https://api.slack.com/apps
  2. Click "Create New App"
  3. Choose "From scratch"
  4. App Name: OnboardingAgent
  5. Pick a workspace: select the workspace you just created
  6. Click "Create App"

  You will land on the app's Basic Information page.
""")
    open_url("https://api.slack.com/apps")
    pause("Create the app and land on its Basic Information page.")

    # ------------------------------------------------------------------
    # Step 3 — Enable Socket Mode + get App-Level Token
    # ------------------------------------------------------------------
    step(3, "Enable Socket Mode (no public URL needed)", """
  Socket Mode lets the bot receive messages without needing a public
  HTTPS endpoint — perfect for local development and testing.

  1. In the left sidebar, click "Socket Mode"
  2. Toggle "Enable Socket Mode" to ON
  3. You will be prompted to create an App-Level Token:
       Token Name: onboarding-socket
       Scopes:     connections:write   (click Add Scope, then select it)
  4. Click "Generate"
  5. Copy the token — it starts with:  xapp-
     (You will NOT be able to see it again after closing this dialog)
""")
    pause("Enable Socket Mode and generate the App-Level Token.")
    slack_app_token = prompt("App-Level Token (xapp-...)")

    # ------------------------------------------------------------------
    # Step 4 — Add OAuth scopes
    # ------------------------------------------------------------------
    step(4, "Add Bot Token scopes", """
  1. In the left sidebar, click "OAuth & Permissions"
  2. Scroll down to "Scopes" → "Bot Token Scopes"
  3. Click "Add an OAuth Scope" and add ALL of the following one by one:

       chat:write          — post messages to channels
       channels:read       — list channels (needed to resolve channel names)
       im:write            — open DM conversations
       im:history          — read DMs sent to the bot
       app_mentions:read   — receive @mentions in channels

  4. Do NOT click Install yet — continue to step 5 first.
""")
    pause("Add all 5 scopes listed above.")

    # ------------------------------------------------------------------
    # Step 5 — Subscribe to events
    # ------------------------------------------------------------------
    step(5, "Subscribe to bot events", """
  1. In the left sidebar, click "Event Subscriptions"
  2. Toggle "Enable Events" to ON
     (With Socket Mode on, no Request URL is needed — Slack will confirm
     automatically)
  3. Expand "Subscribe to bot events"
  4. Click "Add Bot User Event" and add:
       app_mention     — when someone @mentions the bot in a channel
       message.im      — when someone sends the bot a direct message

  5. Click "Save Changes" at the bottom of the page.
""")
    pause("Enable events and add app_mention + message.im.")

    # ------------------------------------------------------------------
    # Step 6 — Install app to workspace
    # ------------------------------------------------------------------
    step(6, "Install the app to your workspace", """
  1. In the left sidebar, click "OAuth & Permissions"
  2. Scroll to the top and click "Install to Workspace"
  3. Click "Allow" on the permission confirmation screen
  4. You will be shown the Bot User OAuth Token — it starts with:  xoxb-
  5. Copy it now.
""")
    pause("Install the app and copy the Bot Token.")
    slack_bot_token = prompt("Bot Token (xoxb-...)")

    # ------------------------------------------------------------------
    # Step 7 — Create HR channel + get channel ID
    # ------------------------------------------------------------------
    step(7, "Create an HR notifications channel and get its ID", """
  1. In your Slack workspace, click "Add channels" in the left sidebar
  2. Click "Create a new channel"
  3. Name it:  hr-onboarding   (private or public — your choice)
  4. Click "Create" then "Done"

  Now get the Channel ID:
  5. Right-click the new channel name in the sidebar
  6. Click "View channel details"
  7. Scroll to the bottom of the popup — you will see:
       Channel ID:  C0XXXXXXXXX
  8. Copy that ID.
""")
    pause("Create the channel and copy its ID.")
    slack_channel_id = prompt("HR channel ID (C...)")

    # ------------------------------------------------------------------
    # Step 8 — Invite the bot to the channel
    # ------------------------------------------------------------------
    step(8, "Invite the bot to the HR channel", """
  The bot must be a member of the channel to post messages to it.

  1. Open the hr-onboarding channel in Slack
  2. Type this message and send it:
       /invite @OnboardingAgent
  3. Slack will confirm the bot has been added.
""")
    pause("Invite the bot to the hr-onboarding channel.")

    # ------------------------------------------------------------------
    # Write .env snippet
    # ------------------------------------------------------------------
    env_content = f"""# Generated by setup_slack.py
CHAT_INTERFACE=slack
SLACK_BOT_TOKEN={slack_bot_token}
SLACK_APP_TOKEN={slack_app_token}
SLACK_CHANNEL_ID={slack_channel_id}
"""

    out_file = ".env.slack"
    with open(out_file, "w") as f:
        f.write(env_content)

    print(f"\n{'=' * 60}")
    print("  All done!")
    print(f"{'=' * 60}")
    print(f"""
  Values written to: {out_file}

  Merge these into your .env file:

    CHAT_INTERFACE=slack
    SLACK_BOT_TOKEN={slack_bot_token[:16]}...
    SLACK_APP_TOKEN={slack_app_token[:16]}...
    SLACK_CHANNEL_ID={slack_channel_id}

  Then start the server:
    python -m onboarding_agent.server

  To test the bot, open Slack and send a direct message to
  @OnboardingAgent, or mention it in #hr-onboarding:
    @OnboardingAgent What's the status of test@example.com?

  To switch back to Teams later:
    Set CHAT_INTERFACE=teams in your .env and restart.
""")


if __name__ == "__main__":
    main()
