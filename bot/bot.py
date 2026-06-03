"""
Option C — one Discord account per Render Background Worker.

Watches log-bot "New Member Joined!" messages (on_message) and forwards a
NEW MEMBER CAPTURED card to one group chat. Simple, no multi-account router.

Each worker: one TOKEN + one CHAT_ID (or TOKEN_CLIENT_N / CHAT_ID_CLIENT_N
with CLIENT_INDEX).

WARNING: Automating a user account (self-botting) violates Discord's ToS.
"""

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


def _client_index() -> int:
    raw = (os.getenv("CLIENT_INDEX") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _load_credentials(index: int) -> tuple[str, int, str]:
    token = (
        (os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN") or "").strip()
        or (os.getenv(f"TOKEN_CLIENT_{index}") or "").strip()
    )
    chat_raw = (
        (os.getenv(f"CHAT_ID_CLIENT_{index}") or "").strip()
        or (os.getenv("CHAT_ID") or "").strip()
        or (os.getenv("CHAT_ID_CLIENT_1") or "").strip()
        or "0"
    )
    label = (
        (os.getenv("CLIENT_NAME") or os.getenv(f"NAME_CLIENT_{index}") or "")
        .strip()
        or f"Client {index}"
    )
    return token, int(chat_raw or 0), label


CLIENT_INDEX = _client_index()
TOKEN, CHAT_ID, CLIENT_NAME = _load_credentials(CLIENT_INDEX)

FIELD_STYLE = [
    ("Date", "date", "📅", C.CYAN),
    ("Time", "time", "⏰", C.CYAN),
    ("Username", "username", "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict) -> None:
    rows = [
        (label, icon, color, data.get(key) or "N/A")
        for label, key, icon, color in FIELD_STYLE
    ]

    title = "✨ NEW MEMBER CAPTURED ✨"
    title_cells = len(title) + 2
    label_width = max(len(label) for label, *_ in rows)
    inner_width = max(
        title_cells,
        max(3 + label_width + 3 + len(str(value)) for *_, value in rows),
    )

    top = f"{C.GOLD}╔{'═' * (inner_width + 2)}╗{C.RESET}"
    sep = f"{C.GOLD}╠{'═' * (inner_width + 2)}╣{C.RESET}"
    bot_line = f"{C.GOLD}╚{'═' * (inner_width + 2)}╝{C.RESET}"
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
    print(bot_line)
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


def collect_message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.append(embed.title or "")
        parts.append(embed.description or "")
        if embed.author:
            parts.append(embed.author.name or "")
        if embed.footer:
            parts.append(embed.footer.text or "")
        for field in embed.fields:
            name = (field.name or "").strip()
            value = (field.value or "").strip()
            if name and value:
                parts.append(f"{name}: {value}")
            else:
                parts.append(name)
                parts.append(value)
    return "\n".join(parts)


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

    server = clean(
        re.search(r"Target\s+Server:\s*(.+)", full_text, re.IGNORECASE)
    ) or clean(re.search(r"Server:\s*(.+)", full_text, re.IGNORECASE))

    return {
        "date": clean(re.search(r"Date:\s*(.+)", full_text, re.IGNORECASE)),
        "time": clean(re.search(r"Time:\s*(.+)", full_text, re.IGNORECASE)),
        "username": clean(re.search(r"Username:\s*(.+)", full_text, re.IGNORECASE)),
        "server_name": server,
        "user_id": clean(re.search(r"User ID:\s*(.+)", full_text, re.IGNORECASE)),
    }


class ScraperClient(discord.Client):
    def __init__(self, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_chat_id = target_chat_id
        self._target_channel = None

    async def on_ready(self):
        print(f"[{CLIENT_NAME}] Logged in as {self.user} (id: {self.user.id})", flush=True)
        print(
            f"[{CLIENT_NAME}] Watching {len(self.guilds)} server(s) for log-bot join messages...",
            flush=True,
        )

        guild_names = sorted(g.name for g in self.guilds)
        preview = ", ".join(guild_names[:10])
        if len(guild_names) > 10:
            preview += f", ... (+{len(guild_names) - 10} more)"
        print(f"[{CLIENT_NAME}] Servers: {preview}", flush=True)

        if not self.target_chat_id:
            print(
                f"[{CLIENT_NAME}] No target chat ID configured; will capture but not forward.",
                flush=True,
            )
            return

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            print(
                f"[{CLIENT_NAME}] Forwarding captures to: {self._target_channel} "
                f"(id: {self.target_chat_id})",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[{CLIENT_NAME}] Could not open chat {self.target_chat_id}: {exc}",
                flush=True,
            )

    async def on_message(self, message):
        data = parse_join_log(collect_message_text(message))
        if data is None:
            return

        process_extracted_data(data)

        channel = self._target_channel
        if channel is None:
            if not self.target_chat_id:
                return
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
            except Exception as exc:
                print(f"[{CLIENT_NAME}] Target chat unavailable: {exc}", flush=True)
                return

        try:
            await channel.send(build_message(data))
            print(
                f"[{CLIENT_NAME}] Forwarded capture for {data.get('username') or 'unknown'}.",
                flush=True,
            )
        except Exception as exc:
            print(f"[{CLIENT_NAME}] Send failed: {exc}", flush=True)


async def main():
    if not TOKEN:
        raise SystemExit(
            "No token set. Use TOKEN, DISCORD_TOKEN, or TOKEN_CLIENT_N on this worker."
        )
    if not CHAT_ID:
        raise SystemExit(
            "No chat ID set. Use CHAT_ID, CHAT_ID_CLIENT_N, or CHAT_ID_CLIENT_1 on this worker."
        )

    print(
        f"[{CLIENT_NAME}] Starting scraper (Option C, chat id {CHAT_ID})...",
        flush=True,
    )
    client = ScraperClient(target_chat_id=CHAT_ID)
    await client.start(TOKEN)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
