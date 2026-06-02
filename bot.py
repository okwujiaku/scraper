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
import sys

import discord
from dotenv import load_dotenv

# Render (and other hosts) buffer stdout; flush each line so logs show live.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Enable ANSI colors on Windows terminals (no-op if colorama isn't installed).
try:
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass


# ---------------------------------------------------------------------------
# LIBRARY COMPATIBILITY PATCH
# ---------------------------------------------------------------------------
# discord.py-self's parse_ready_supplemental crashes when Discord sends
# "pending_payments": null (the .get(..., []) default never applies because the
# key exists with a None value), raising:
#     TypeError: 'NoneType' object is not iterable
# We wrap the original parser so a None payload is treated as an empty list,
# keeping the connection alive instead of killing the whole gather().
try:
    _orig_parse_ready_supplemental = (
        discord.state.ConnectionState.parse_ready_supplemental
    )

    def _safe_parse_ready_supplemental(self, extra_data, *args, **kwargs):
        # pending_payments lives on self._ready_data, not extra_data.
        ready = getattr(self, "_ready_data", None)
        if isinstance(ready, dict) and ready.get("pending_payments") is None:
            ready["pending_payments"] = []
        return _orig_parse_ready_supplemental(self, extra_data, *args, **kwargs)

    discord.state.ConnectionState.parse_ready_supplemental = (
        _safe_parse_ready_supplemental
    )
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


def load_accounts():
    """Load every TOKEN_CLIENT_N / CHAT_ID_CLIENT_N pair from the environment."""
    accounts = []
    for i in range(1, 21):
        token = (os.getenv(f"TOKEN_CLIENT_{i}") or "").strip()
        if not token:
            continue

        chat_id_raw = (os.getenv(f"CHAT_ID_CLIENT_{i}") or "").strip()
        try:
            chat_id = int(chat_id_raw) if chat_id_raw else 0
        except ValueError:
            raise SystemExit(
                f"CHAT_ID_CLIENT_{i} must be a numeric Discord channel ID, got: {chat_id_raw!r}"
            )

        accounts.append(
            {
                "index": i,
                "name": (os.getenv(f"NAME_CLIENT_{i}") or f"Client {i}").strip(),
                "token": token,
                "chat_id": chat_id,
            }
        )
    return accounts


ACCOUNTS = load_accounts()


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


def process_extracted_data(data: dict, client_name: str = ""):
    """Print a parsed join event to the terminal in a colorful, premium box."""
    prefix = f"[{client_name}] " if client_name else ""
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
    if prefix:
        print(f"{prefix}capture detected", flush=True)
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
        self._target_channel = None

    async def on_ready(self):
        print(f"[{self.name}] Logged in as {self.user} (id: {self.user.id})", flush=True)
        print(
            f"[{self.name}] Watching {len(self.guilds)} server(s) for log-bot join messages...",
            flush=True,
        )

        if not self.target_chat_id:
            print(f"[{self.name}] No target chat ID configured; will capture but not forward.", flush=True)
            return

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            print(f"[{self.name}] Forwarding captures to: {self._target_channel}", flush=True)
        except Exception as exc:
            print(
                f"[{self.name}] Could not open target chat {self.target_chat_id}: {exc}",
                flush=True,
            )

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

            process_extracted_data(data, client_name=self.name)

            if not self.target_chat_id:
                return

            channel = self._target_channel
            if channel is None:
                try:
                    channel = await self.fetch_channel(self.target_chat_id)
                    self._target_channel = channel
                except Exception as exc:
                    print(
                        f"[{self.name}] Could not find target chat {self.target_chat_id}: {exc}",
                        flush=True,
                    )
                    return

            try:
                await channel.send(build_message(data))
                print(f"[{self.name}] Forwarded capture for {data.get('username') or 'unknown'}.", flush=True)
            except Exception as exc:
                print(f"[{self.name}] Failed to send to chat {self.target_chat_id}: {exc}", flush=True)


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

async def run_client(account: dict):
    """Start one account; keep other accounts running if this one fails."""
    client = ScraperClient(
        name=account["name"],
        target_chat_id=account["chat_id"],
    )
    try:
        await client.start(account["token"])
    except Exception as exc:
        print(f"[{account['name']}] Stopped: {exc}", flush=True)


async def main():
    print("Starting scraper...", flush=True)

    if not ACCOUNTS:
        raise SystemExit(
            "No accounts found. Add TOKEN_CLIENT_1 / CHAT_ID_CLIENT_1 "
            "(and TOKEN_CLIENT_2 / CHAT_ID_CLIENT_2, etc.) to your environment."
        )

    tasks = []
    for account in ACCOUNTS:
        if not account["chat_id"]:
            raise SystemExit(
                f"[{account['name']}] TOKEN_CLIENT_{account['index']} is set but "
                f"CHAT_ID_CLIENT_{account['index']} is missing. Add it in Render "
                f"(Dashboard → your service → Environment), then redeploy."
            )

        print(
            f"[{account['name']}] Connecting (target chat {account['chat_id']})...",
            flush=True,
        )
        tasks.append(asyncio.create_task(run_client(account)))

    print(f"Launching {len(tasks)} account(s)...", flush=True)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
