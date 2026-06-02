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

# Enable ANSI colors on Windows terminals (no-op if colorama isn't installed).
try:
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass


# ---------------------------------------------------------------------------
# TERMINAL STYLING
# ---------------------------------------------------------------------------

class C:
    """Small ANSI color palette for a premium, colorful terminal layout."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GOLD = "\033[38;5;220m"
    CYAN = "\033[38;5;51m"
    GREEN = "\033[38;5;48m"
    PINK = "\033[38;5;213m"
    PURPLE = "\033[38;5;141m"
    GRAY = "\033[38;5;245m"
    WHITE = "\033[97m"


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

# Icons paired with each field for a richer, more scannable layout.
FIELD_STYLE = [
    ("Date",          "date",        "📅", C.CYAN),
    ("Time",          "time",        "⏰", C.CYAN),
    ("Username",      "username",    "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict):
    """Print a parsed join event to the terminal in a colorful, premium box."""
    rows = [(label, icon, color, data.get(key) or "N/A")
            for label, key, icon, color in FIELD_STYLE]

    title = "✨ NEW MEMBER CAPTURED ✨"
    title_cells = len(title) + 2  # +2 for the two emoji rendering as 2 cells each

    label_width = max(len(label) for label, *_ in rows)
    # Plain content width (icon counts as 2 cells + 1 space) drives alignment.
    inner_width = max(
        title_cells,
        max(3 + label_width + 3 + len(str(value)) for *_, value in rows),
    )

    top = f"{C.GOLD}╔{'═' * (inner_width + 2)}╗{C.RESET}"
    sep = f"{C.GOLD}╠{'═' * (inner_width + 2)}╣{C.RESET}"
    bot = f"{C.GOLD}╚{'═' * (inner_width + 2)}╝{C.RESET}"
    bar = f"{C.GOLD}║{C.RESET}"

    title_pad = inner_width - title_cells
    left = title_pad // 2
    right = title_pad - left

    print()
    print(top)
    print(f"{bar} {' ' * left}{C.BOLD}{C.PINK}{title}{C.RESET}{' ' * right} {bar}")
    print(sep)
    for label, icon, color, value in rows:
        plain_len = 3 + label_width + 3 + len(str(value))  # icon+sp + label + " : "
        pad = " " * (inner_width - plain_len)
        print(
            f"{bar} {icon} {color}{label:<{label_width}}{C.RESET}"
            f"{C.GRAY} : {C.RESET}{C.WHITE}{value}{C.RESET}{pad} {bar}"
        )
    print(bot)
    print()


def build_message(data: dict) -> str:
    """Build a clean, premium Discord message using markdown + icons.

    User accounts (self-bots) cannot send rich embeds, so the look is recreated
    with bold markdown and emoji icons. Username uses inline code so it stays
    copy-friendly (tap-to-copy) without showing a bulky code-block write-up.
    Target Server is intentionally the last line of the card.
    """
    card = [
        "🎉 **NEW MEMBER CAPTURED** 🎉",
        f"📅 **Date:** {data.get('date') or 'N/A'}",
        f"⏰ **Time:** {data.get('time') or 'N/A'}",
        f"👤 **Username:** `{data.get('username') or 'N/A'}`",
        f"🆔 **User ID:** {data.get('user_id') or 'N/A'}",
        f"🏠 **Target Server:** {data.get('server_name') or 'N/A'}",
    ]

    # Trailing blank line + divider gives clear spacing between stacked results.
    return "\n".join(card) + "\n\u200b\n" + "─" * 30


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
            user_id_match = re.search(r"User ID:\s*(.+)", full_text)

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
                "user_id": clean(user_id_match),
            }

            process_extracted_data(data)

            # Forward the captured event to this client's dedicated group chat.
            channel = self.get_channel(self.target_chat_id)
            if channel is None:
                print(f"[{self.name}] Could not find target chat {self.target_chat_id}; skipping send.")
            else:
                try:
                    await channel.send(build_message(data))
                except Exception as exc:
                    print(f"[{self.name}] Failed to send to chat {self.target_chat_id}: {exc}")


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
