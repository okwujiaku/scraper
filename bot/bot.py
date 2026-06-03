"""
Single-account Discord join-log scraper.

Watches for third-party log-bot "New Member Joined!" messages and forwards
parsed fields to one group chat. Deploy one Render Background Worker per customer;
each worker only needs TOKEN and CHAT_ID in its environment.

WARNING: Automating a user account (self-botting) violates Discord's ToS.
"""

import asyncio
import os
import re
import sys

import discord
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

try:
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass

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


load_dotenv()

TOKEN = (os.getenv("TOKEN") or "").strip()
CHAT_ID = int((os.getenv("CHAT_ID") or "0").strip() or 0)
CLIENT_NAME = (os.getenv("CLIENT_NAME") or "scraper").strip()
# Sends one message on startup so you can confirm the group chat works (set false to disable).
SEND_STARTUP_PING = (os.getenv("SEND_STARTUP_PING") or "true").strip().lower() in (
    "1", "true", "yes", "on",
)

FIELD_STYLE = [
    ("Date",          "date",        "📅", C.CYAN),
    ("Time",          "time",        "⏰", C.CYAN),
    ("Username",      "username",    "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict):
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
    print(f"[{CLIENT_NAME}] capture detected", flush=True)
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
    has_user = "username:" in lowered and ("user id:" in lowered or "userid:" in lowered)
    has_join = any(
        phrase in lowered
        for phrase in (
            "new member joined",
            "member joined!",
            "member joined",
            "new member join",
            "user joined",
        )
    )
    return has_user and has_join


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


class ScraperClient(discord.Client):
    def __init__(self, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_chat_id = target_chat_id
        self._target_channel = None

    async def on_ready(self):
        print(f"[{CLIENT_NAME}] Logged in as {self.user} (id: {self.user.id})", flush=True)
        print(f"[{CLIENT_NAME}] Monitoring {len(self.guilds)} server(s).", flush=True)
        guild_names = sorted(g.name for g in self.guilds)
        preview = ", ".join(guild_names[:10])
        if len(guild_names) > 10:
            preview += f", ... (+{len(guild_names) - 10} more)"
        print(f"[{CLIENT_NAME}] Servers: {preview}", flush=True)

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            print(
                f"[{CLIENT_NAME}] Forwarding to: {self._target_channel} "
                f"(id: {self._target_channel.id})",
                flush=True,
            )
            if SEND_STARTUP_PING:
                await self._send_startup_ping()
        except Exception as exc:
            print(f"[{CLIENT_NAME}] Could not open chat {self.target_chat_id}: {exc}", flush=True)

    async def _send_startup_ping(self) -> None:
        channel = self._target_channel
        if channel is None:
            return
        ping = (
            f"✅ **{CLIENT_NAME} scraper is online**\n"
            f"Monitoring **{len(self.guilds)}** server(s). "
            f"New member captures will appear here."
        )
        try:
            await channel.send(ping)
            print(f"[{CLIENT_NAME}] Startup message sent to group chat.", flush=True)
        except Exception as exc:
            print(f"[{CLIENT_NAME}] Startup message failed: {exc}", flush=True)

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

        process_extracted_data(data)

        channel = self._target_channel
        if channel is None:
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
            except Exception as exc:
                print(f"[{CLIENT_NAME}] Target chat unavailable: {exc}", flush=True)
                return

        try:
            msg = await channel.send(build_message(data))
            print(
                f"[{CLIENT_NAME}] Forwarded capture for {data.get('username') or 'unknown'} "
                f"(message id: {msg.id}).",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{CLIENT_NAME}] Send failed for {data.get('username')}: {exc}",
                flush=True,
            )
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
                msg = await channel.send(build_message(data))
                print(
                    f"[{CLIENT_NAME}] Retry send OK (message id: {msg.id}).",
                    flush=True,
                )
            except Exception as retry_exc:
                print(f"[{CLIENT_NAME}] Retry send failed: {retry_exc}", flush=True)


async def main():
    if not TOKEN:
        raise SystemExit("TOKEN is not set. Add it to your environment or .env file.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID is not set. Add your group chat ID to the environment.")

    print(f"[{CLIENT_NAME}] Starting scraper...", flush=True)
    client = ScraperClient(target_chat_id=CHAT_ID)
    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
