"""
Discord self-bot that watches for third-party log-bot "New Member Joined!"
text blocks, extracts the fields with regex, prints them to the local terminal
in a clean boxed layout, and forwards them to a dedicated group chat.

Supports running multiple user accounts concurrently, each forwarding to its
own target group chat, via asyncio.gather.

WARNING: Automating a user account (self-botting) violates Discord's Terms of
Service and may result in your account being banned. Use at your own risk.
"""

import asyncio
import os
import re

import discord
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Load secrets from the local .env file (never commit .env to git).
load_dotenv()

# Each account runs independently with its own token and target group chat.
# Add more entries here to scale up; populate the matching keys in your .env.
ACCOUNTS = [
    {
        "name": "Client 1",
        "token": os.getenv("TOKEN_CLIENT_1"),
        "chat_id": int(os.getenv("CHAT_ID_CLIENT_1") or 0),
    },
    {
        "name": "Client 2",
        "token": os.getenv("TOKEN_CLIENT_2"),
        "chat_id": int(os.getenv("CHAT_ID_CLIENT_2") or 0),
    },
    {
        "name": "Client 3",
        "token": os.getenv("TOKEN_CLIENT_3"),
        "chat_id": int(os.getenv("CHAT_ID_CLIENT_3") or 0),
    },
    {
        "name": "Client 4",
        "token": os.getenv("TOKEN_CLIENT_4"),
        "chat_id": int(os.getenv("CHAT_ID_CLIENT_4") or 0),
    },
    {
        "name": "Client 5",
        "token": os.getenv("TOKEN_CLIENT_5"),
        "chat_id": int(os.getenv("CHAT_ID_CLIENT_5") or 0),
    },
]


# ---------------------------------------------------------------------------
# DATA HANDLER
# ---------------------------------------------------------------------------

def build_box(data: dict) -> str:
    """Return a parsed join event rendered as a clean, boxed layout string."""
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

    lines = [
        border,
        "| " + "NEW MEMBER CAPTURED".center(inner_width) + " |",
        border,
    ]
    for (label, _), value in zip(rows, values):
        line = f"{label:<{label_width}} : {value}"
        lines.append("| " + line.ljust(inner_width) + " |")
    lines.append(border)

    return "\n".join(lines)


def process_extracted_data(data: dict):
    """Print a parsed join event to the terminal in a clean, boxed layout."""
    print()
    print(build_box(data))
    print()


# ---------------------------------------------------------------------------
# DISCORD CLIENT
# ---------------------------------------------------------------------------

class ScraperClient(discord.Client):
    """A self-bot instance that scrapes join events and forwards them to a
    dedicated group chat identified by ``target_chat_id``."""

    def __init__(self, name: str, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name
        self.target_chat_id = target_chat_id

    async def on_ready(self):
        print(f"[{self.name}] Logged in as {self.user} (id: {self.user.id})")
        print(f"[{self.name}] Capturing all new-member joins across every visible server...")

    async def on_message(self, message):
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

            # Forward the captured event to this client's dedicated group chat.
            channel = self.get_channel(self.target_chat_id)
            if channel is None:
                print(f"[{self.name}] Could not find target chat {self.target_chat_id}; skipping send.")
            else:
                await channel.send("```\n" + build_box(data) + "\n```")


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

async def main():
    tasks = []
    for account in ACCOUNTS:
        token = account.get("token")
        if not token:
            print(f"[{account.get('name', 'Unknown')}] No token set; skipping.")
            continue

        client = ScraperClient(
            name=account["name"],
            target_chat_id=account["chat_id"],
        )
        tasks.append(client.start(token))

    if not tasks:
        raise SystemExit(
            "No valid accounts found. Add TOKEN_CLIENT_1 / CHAT_ID_CLIENT_1 "
            "(etc.) to your .env file."
        )

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
