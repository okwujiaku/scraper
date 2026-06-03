"""
Discord self-bot that watches for third-party log-bot "New Member Joined!"
text blocks, extracts the fields with regex, prints them to the terminal, and
forwards them to a dedicated group chat.

Multiple accounts run at once (asyncio.gather). Each account only forwards joins
it sees in servers that account belongs to — join each brand's servers with the
matching Discord account (Pikanto → Auto Wise, klentozz → Stevo, etc.).

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
try:
    _orig_parse_ready_supplemental = (
        discord.state.ConnectionState.parse_ready_supplemental
    )

    def _safe_parse_ready_supplemental(self, extra_data, *args, **kwargs):
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
    RESET = "\033[0m"
    BOLD = "\033[1m"
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

FIELD_STYLE = [
    ("Date",          "date",        "📅", C.CYAN),
    ("Time",          "time",        "⏰", C.CYAN),
    ("Username",      "username",    "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict, client_name: str = ""):
    prefix = f"[{client_name}] " if client_name else ""
    rows = [(label, icon, color, data.get(key) or "N/A")
            for label, key, icon, color in FIELD_STYLE]

    title = "✨ NEW MEMBER CAPTURED ✨"
    title_cells = len(title) + 2

    label_width = max(len(label) for label, *_ in rows)
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
        plain_len = 3 + label_width + 3 + len(str(value))
        pad = " " * (inner_width - plain_len)
        print(
            f"{bar} {icon} {color}{label:<{label_width}}{C.RESET}"
            f"{C.GRAY} : {C.RESET}{C.WHITE}{value}{C.RESET}{pad} {bar}"
        )
    print(bot)
    print()


def build_message(data: dict) -> str:
    card = [
        "🎉 **NEW MEMBER CAPTURED** 🎉",
        f"📅 **Date:** {data.get('date') or 'N/A'}",
        f"⏰ **Time:** {data.get('time') or 'N/A'}",
        f"👤 **Username:** `{data.get('username') or 'N/A'}`",
        f"🆔 **User ID:** {data.get('user_id') or 'N/A'}",
        f"🏠 **Target Server:** {data.get('server_name') or 'N/A'}",
    ]
    return "\n".join(card) + "\n\u200b\n" + "─" * 30


def is_join_log(text: str) -> bool:
    lowered = text.lower()
    return (
        "username:" in lowered
        and "user id:" in lowered
        and ("new member joined" in lowered or "member joined!" in lowered)
    )


def parse_join_log(full_text: str) -> dict | None:
    if not is_join_log(full_text):
        return None

    def clean(match):
        if not match:
            return None
        return match.group(1).strip().replace("**", "").replace("`", "").strip()

    return {
        "date": clean(re.search(r"Date:\s*(.+)", full_text, re.IGNORECASE)),
        "time": clean(re.search(r"Time:\s*(.+)", full_text, re.IGNORECASE)),
        "username": clean(re.search(r"Username:\s*(.+)", full_text, re.IGNORECASE)),
        "server_name": clean(re.search(r"Server:\s*(.+)", full_text, re.IGNORECASE)),
        "user_id": clean(re.search(r"User ID:\s*(.+)", full_text, re.IGNORECASE)),
    }


# ---------------------------------------------------------------------------
# DISCORD CLIENT
# ---------------------------------------------------------------------------

class ScraperClient(discord.Client):
    """Forwards join captures only from servers this account belongs to."""

    def __init__(self, name: str, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name
        self.target_chat_id = target_chat_id
        self._target_channel = None

    async def on_ready(self):
        print(f"[{self.name}] Logged in as {self.user} (id: {self.user.id})", flush=True)
        print(
            f"[{self.name}] Monitoring {len(self.guilds)} server(s) — "
            f"new joins in any of these can be forwarded.",
            flush=True,
        )

        guild_names = sorted(g.name for g in self.guilds)
        preview = ", ".join(guild_names[:12])
        if len(guild_names) > 12:
            preview += f", ... (+{len(guild_names) - 12} more)"
        print(f"[{self.name}] Servers: {preview}", flush=True)

        if not self.target_chat_id:
            print(f"[{self.name}] No target chat ID configured.", flush=True)
            return

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            print(f"[{self.name}] Forwarding to: {self._target_channel}", flush=True)
        except Exception as exc:
            print(
                f"[{self.name}] Could not open target chat {self.target_chat_id}: {exc}",
                flush=True,
            )

    async def on_message(self, message):
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

        data = parse_join_log("\n".join(parts))
        if data is None:
            return

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
            print(
                f"[{self.name}] Forwarded capture for {data.get('username') or 'unknown'}.",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{self.name}] Failed to send to chat {self.target_chat_id}: {exc}",
                flush=True,
            )


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

async def run_client(account: dict):
    client = ScraperClient(
        name=account["name"],
        target_chat_id=account["chat_id"],
    )
    try:
        await client.start(account["token"])
    except Exception as exc:
        print(f"[{account['name']}] Stopped: {exc}", flush=True)


async def main():
    print("Starting scraper (each account forwards only what it sees)...", flush=True)

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
