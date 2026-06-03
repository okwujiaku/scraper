"""
Native join listener (Option C) — Smart Tech style.

Listens for on_member_join only. Forwards realtime joins to CHAT_ID_CLIENT_1.
Guild sync replays (old joined_at) are ignored.

WARNING: Automating a user account (self-botting) violates Discord's ToS.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

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
    _orig = discord.state.ConnectionState.parse_ready_supplemental

    def _safe_parse_ready_supplemental(self, extra_data, *args, **kwargs):
        ready = getattr(self, "_ready_data", None)
        if isinstance(ready, dict) and ready.get("pending_payments") is None:
            ready["pending_payments"] = []
        return _orig(self, extra_data, *args, **kwargs)

    discord.state.ConnectionState.parse_ready_supplemental = _safe_parse_ready_supplemental
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
# Only forward joins that happened within this many seconds (blocks guild-sync replays)
MAX_JOIN_AGE_SECONDS = int((os.getenv("MAX_JOIN_AGE_SECONDS") or "120").strip() or 120)

CARD_SEPARATOR = "\n----------------------------------------\n"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_join_time(when: datetime | None) -> tuple[str, str]:
    if when is None:
        when = datetime.now(timezone.utc)
    local = _utc(when).astimezone()
    return local.strftime("%B %d, %Y"), local.strftime("%I:%M:%S %p").lstrip("0")


def build_capture_message(
    username: str,
    user_id: int,
    server_name: str,
    date_str: str,
    time_str: str,
) -> str:
    """Smart Tech layout with spacing between fields and a divider after each card."""
    return (
        f"📅 **Date:** {date_str}\n"
        f"\n"
        f"🕒 **Time:** {time_str}\n"
        f"\n"
        f"👤 **Username:** `{username}`\n"
        f"\n"
        f"🆔 **User ID:** {user_id}\n"
        f"\n"
        f"🏠 **Server:** {server_name}\n"
        f"\n"
        f"🎉 **New Member Joined!**"
    )


def build_startup_message(session_label: str) -> str:
    date_str, time_str = format_join_time(datetime.now(timezone.utc))
    return (
        "✅ **Scraper online**\n"
        f"\n"
        f"Session **{session_label}** is listening for new joins.\n"
        f"\n"
        f"📅 **Date:** {date_str}\n"
        f"\n"
        f"🕒 **Time:** {time_str}"
    )


async def dispatch_card(channel: discord.abc.Messageable, content: str) -> discord.Message:
    """Send card then a separate divider message for clean spacing in chat."""
    msg = await channel.send(content)
    await channel.send(CARD_SEPARATOR)
    return msg


def is_realtime_join(member: discord.Member, live_after: datetime) -> bool:
    """True only for joins that just happened — not guild-sync replays from years ago."""
    if member.joined_at is None:
        return False
    joined = _utc(member.joined_at)
    if joined < live_after:
        return False
    age = (datetime.now(timezone.utc) - joined).total_seconds()
    return age <= MAX_JOIN_AGE_SECONDS


class NativeJoinClient(discord.Client):
    def __init__(self, output_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_chat_id = output_chat_id
        self._output_channel: discord.abc.Messageable | None = None
        self._ready_once = False
        self._live_after: datetime | None = None
        self._forwarded: set[tuple[int, int]] = set()
        self._send_lock = asyncio.Lock()

    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        self._live_after = datetime.now(timezone.utc)

        _log(f"[Success] Logged in as {self.user}")
        _log(f"[Ready] Live capture from {self._live_after.isoformat()}")

        try:
            self._output_channel = await asyncio.wait_for(
                self.fetch_channel(self.output_chat_id),
                timeout=30,
            )
            _log(f"[Ready] Output chat: {self._output_channel}")
        except Exception as exc:
            _log(f"[Error] Could not open output chat: {exc}")
            return

        if SEND_STARTUP_PING:
            try:
                async with self._send_lock:
                    await self._output_channel.send(
                        build_startup_message(str(self.user))
                    )
                _log("[Ready] Startup message sent.")
            except Exception as exc:
                _log(f"[Error] Startup message failed: {exc}")

        # Brief pause so guild-sync member_join bursts finish before we accept joins
        await asyncio.sleep(15)
        self._live_after = datetime.now(timezone.utc)
        _log("[Ready] Now accepting realtime joins only.")

    async def on_member_join(self, member: discord.Member):
        if member.bot or self._live_after is None:
            return

        if not is_realtime_join(member, self._live_after):
            return

        guild_id = member.guild.id if member.guild else 0
        key = (member.id, guild_id)
        if key in self._forwarded:
            return
        self._forwarded.add(key)

        date_str, time_str = format_join_time(member.joined_at)
        username = member.name
        user_id = member.id
        server_name = member.guild.name if member.guild else "Unknown"

        _log(f"[Join] {username} ({user_id}) → {server_name} @ {date_str} {time_str}")

        channel = self._output_channel
        if channel is None:
            try:
                channel = await self.fetch_channel(self.output_chat_id)
                self._output_channel = channel
            except Exception as exc:
                _log(f"[Error] Output chat unavailable: {exc}")
                return

        content = build_capture_message(
            username, user_id, server_name, date_str, time_str
        )
        try:
            async with self._send_lock:
                msg = await channel.send(content)
            _log(f"[Sent] Capture forwarded (msg {msg.id}).")
        except Exception as exc:
            _log(f"[Error] Forward failed: {exc}")


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("[Engine] Starting native join listener...")
    client = NativeJoinClient(output_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
