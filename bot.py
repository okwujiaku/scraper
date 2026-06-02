"""
Discord self-bot that watches for third-party log-bot "New Member Joined!"
text blocks, extracts the fields with regex, and prints them to the local
terminal in a clean boxed layout.

WARNING: Automating a user account (self-botting) violates Discord's Terms of
Service and may result in your account being banned. Use at your own risk.
"""

import os
import re

import discord
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Load secrets from the local .env file (never commit .env to git).
load_dotenv()

# Your Discord USER token (NOT a bot token). Stored in .env, kept out of git.
USER_TOKEN = os.getenv("USER_TOKEN")


# ---------------------------------------------------------------------------
# DATA HANDLER
# ---------------------------------------------------------------------------

def process_extracted_data(data: dict):
    """Print a parsed join event to the terminal in a clean, boxed layout."""
    rows = [
        ("Date",          data.get("date")),
        ("Time",          data.get("time")),
        ("Username",      data.get("username")),
        ("Target Server", data.get("server_name")),
    ]

    # Width is sized to the longest value so the box always lines up neatly.
    label_width = max(len(label) for label, _ in rows)
    values = [str(value) if value is not None else "N/A" for _, value in rows]
    inner_width = max(len("NEW MEMBER CAPTURED"),
                      max(label_width + 2 + len(v) for v in values))

    border = "+" + "-" * (inner_width + 2) + "+"

    print()
    print(border)
    print("| " + "NEW MEMBER CAPTURED".center(inner_width) + " |")
    print(border)
    for (label, _), value in zip(rows, values):
        line = f"{label:<{label_width}} : {value}"
        print("| " + line.ljust(inner_width) + " |")
    print(border)
    print()


# ---------------------------------------------------------------------------
# DISCORD CLIENT
# ---------------------------------------------------------------------------

client = discord.Client()


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (id: {client.user.id})")
    print("Capturing all new-member joins across every visible server...")


@client.event
async def on_message(message):
    # Collect text from the plain content and from every embed (title,
    # description, author, footer, and each field name/value) so we catch log
    # bots that post join info inside rich embeds.
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.append(embed.title or "")
        parts.append(embed.description or "")
        if embed.author:
            parts.append(embed.author.name or "")
        if embed.footer:
            parts.append(embed.footer.text or "")
        for field in embed.fields:
            parts.append(field.name or "")
            parts.append(field.value or "")

    full_text = "\n".join(parts)

    # Key off the distinctive label phrases inside the combined text.
    if "Username:" in full_text and "User ID:" in full_text and "New Member Joined!" in full_text:
        date_match = re.search(r"Date:\s*(.+)", full_text)
        time_match = re.search(r"Time:\s*(.+)", full_text)
        username_match = re.search(r"Username:\s*(.+)", full_text)
        server_match = re.search(r"Server:\s*(.+)", full_text)

        def clean(match):
            # Strip Discord markdown clutter (** bold and ` code) from a value.
            if not match:
                return None
            return match.group(1).strip().replace("**", "").replace("`", "").strip()

        data = {
            "date": clean(date_match),
            "time": clean(time_match),
            "username": clean(username_match),
            "server_name": clean(server_match),
        }

        process_extracted_data(data)


if __name__ == "__main__":
    if not USER_TOKEN:
        raise SystemExit(
            "USER_TOKEN is not set. Create a .env file in this folder with a "
            "line like: USER_TOKEN=your_token_here"
        )
    client.run(USER_TOKEN)
