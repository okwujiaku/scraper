"""
Universal single-client join capture engine (Option C).

Passive live listener only — no startup channel scans or background polls.
Deploy one Render Background Worker per customer with:
  - DISCORD_TOKEN
  - CHAT_ID_CLIENT_1

WARNING: Automating a user account (self-botting) violates Discord's ToS.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone

import discord
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

try:
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass

# discord.py-self: pending_payments null crash on READY_SUPPLEMENTAL
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


load_dotenv()

DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN") or "").strip()
CHAT_ID = int(
    (os.getenv("CHAT_ID_CLIENT_1") or os.getenv("CHAT_ID") or "0").strip() or 0
)
SEND_STARTUP_PING = (os.getenv("SEND_STARTUP_PING") or "true").strip().lower() in (
    "1", "true", "yes", "on",
)

_NATIVE_JOIN_TYPES: tuple[discord.MessageType, ...] = tuple(
    t
    for t in (
        getattr(discord.MessageType, "new_member", None),
        getattr(discord.MessageType, "member_join", None),
    )
    if t is not None
)


def _log(label: str, message: str) -> None:
    print(f"[{label}] {message}", flush=True)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_timestamp(dt: datetime | None) -> tuple[str, str]:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return local.strftime("%B %d, %Y"), local.strftime("%I:%M:%S %p").lstrip("0")


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
            parts.append(field.name or "")
            parts.append(field.value or "")
    return "\n".join(parts)


def _field_map(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("**", "").replace("`", "")
        value = value.strip().replace("**", "").replace("`", "")
        if key and value:
            fields[key] = value
    return fields


def parse_custom_log(text: str) -> dict | None:
    lowered = text.lower()
    fields = _field_map(text)

    has_user = "username:" in lowered or "username" in fields
    has_id = any(
        k in lowered or k in fields
        for k in ("user id:", "userid:", "user id", "userid")
    )
    has_join = any(
        phrase in lowered
        for phrase in (
            "new member joined",
            "member joined",
            "member join",
            "user joined",
            "joined the server",
            "has joined",
            "just joined",
        )
    )
    title_join = "join" in lowered and "member" in lowered

    if not (has_user and has_id and (has_join or title_join)):
        return None

    def from_regex(pattern: str):
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().replace("**", "").replace("`", "").strip()

    username = fields.get("username") or from_regex(r"Username:\s*(.+)")
    user_id = (
        fields.get("user id")
        or fields.get("userid")
        or fields.get("id")
        or from_regex(r"User\s*ID:\s*(.+)")
    )
    server_name = (
        fields.get("target server")
        or fields.get("server")
        or fields.get("server name")
        or from_regex(r"(?:Target\s+)?Server:\s*(.+)")
    )

    if not username:
        return None

    return {
        "username": username,
        "user_id": user_id,
        "server_name": server_name,
    }


def parse_native_join(message: discord.Message) -> dict | None:
    if message.type not in _NATIVE_JOIN_TYPES:
        return None
    if not message.author:
        return None

    date_str, time_str = _format_timestamp(message.created_at)
    return {
        "date": date_str,
        "time": time_str,
        "username": message.author.display_name or str(message.author),
        "user_id": str(message.author.id),
        "server_name": message.guild.name if message.guild else "N/A",
    }


def build_capture_card(data: dict) -> str:
    """Markdown card — user tokens cannot send embeds (API error 50006)."""
    return (
        "🎉 **NEW MEMBER CAPTURED** 🎉\n"
        f"📅 **Date:** {data.get('date') or 'N/A'}\n"
        f"⏰ **Time:** {data.get('time') or 'N/A'}\n"
        f"🆔 **User ID:** {data.get('user_id') or 'N/A'}\n"
        f"👤 **Username:** `{data.get('username') or 'N/A'}`\n"
        f"🏠 **Target Server:** {data.get('server_name') or 'N/A'}\n"
        "\n_Tap the username above to copy._\n\u200b\n"
        + "─" * 30
    )


def build_startup_card(session_label: str) -> str:
    return (
        "✅ **Scraper online**\n"
        f"Logged in as **{session_label}**.\n"
        "Listening for new joins — captures will appear here instantly."
    )


def extract_capture(message: discord.Message) -> tuple[dict | None, str]:
    native = parse_native_join(message)
    if native:
        return native, "native"

    custom = parse_custom_log(collect_message_text(message))
    if custom:
        d, t = _format_timestamp(message.created_at)
        custom["date"] = d
        custom["time"] = t
        if not custom.get("server_name") and message.guild:
            custom["server_name"] = message.guild.name
        return custom, "custom-log"

    return None, ""


class UniversalJoinClient(discord.Client):
    def __init__(self, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_chat_id = target_chat_id
        self._output_channel: discord.abc.Messageable | None = None
        self._monitor_from: datetime | None = None
        self._seen_ids: set[int] = set()
        self._ready_once = False
        self._captures = 0

    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        self._monitor_from = datetime.now(timezone.utc)

        print(f"[Success] Logged in as {self.user}", flush=True)
        _log(str(self.user), f"Monitoring {len(self.guilds)} server(s) (live only).")

        try:
            self._output_channel = await asyncio.wait_for(
                self.fetch_channel(self.target_chat_id),
                timeout=30,
            )
            _log(str(self.user), f"Output chat: {self._output_channel}")
        except Exception as exc:
            _log(str(self.user), f"Could not open output chat: {exc}")
            return

        if SEND_STARTUP_PING:
            try:
                await self._output_channel.send(build_startup_card(str(self.user)))
                _log(str(self.user), "Startup card sent.")
            except Exception as exc:
                _log(str(self.user), f"Startup send failed: {exc}")

    async def on_message(self, message: discord.Message):
        if message.id in self._seen_ids:
            return
        self._seen_ids.add(message.id)
        if len(self._seen_ids) > 8000:
            self._seen_ids = set(list(self._seen_ids)[-4000:])

        if message.author and self.user and message.author.id == self.user.id:
            return

        if self._monitor_from and _utc(message.created_at) < self._monitor_from:
            return

        data, kind = extract_capture(message)
        if data is None:
            return

        channel = self._output_channel
        if channel is None:
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._output_channel = channel
            except Exception as exc:
                _log(str(self.user), f"Output chat unavailable: {exc}")
                return

        guild_name = message.guild.name if message.guild else "DM"
        ch_name = getattr(message.channel, "name", "dm")
        _log(
            str(self.user),
            f"Capture ({kind}) {data.get('username')} @ {guild_name}/#{ch_name}",
        )

        try:
            sent = await channel.send(build_capture_card(data))
            self._captures += 1
            _log(str(self.user), f"Forwarded (msg {sent.id}, total {self._captures}).")
        except Exception as exc:
            _log(str(self.user), f"Forward failed: {exc}")


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("engine", "Starting passive join listener...")
    client = UniversalJoinClient(target_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
