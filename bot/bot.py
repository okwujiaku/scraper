"""
Universal single-client join capture engine (Option C).

Deploy one Render Background Worker per customer. Each worker uses only:
  - DISCORD_TOKEN  (user account token)
  - CHAT_ID_CLIENT_1 (target group chat ID)

Detects joins via custom log-bot text OR native Discord member-join messages,
then forwards a premium markdown card to the configured group chat.
(User accounts cannot send API embeds; formatted text is used instead.)

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
HISTORY_POLL_SECONDS = int((os.getenv("HISTORY_POLL_SECONDS") or "45").strip() or 45)
POLL_HISTORY_LIMIT = int((os.getenv("POLL_HISTORY_LIMIT") or "3").strip() or 3)
SEND_STARTUP_PING = (os.getenv("SEND_STARTUP_PING") or "true").strip().lower() in (
    "1", "true", "yes", "on",
)

CHANNEL_KEYWORDS = ("welcome", "joins", "gate", "logs", "member", "general")

# discord.py / discord.py-self name this differently across versions
_NATIVE_JOIN_TYPES: tuple[discord.MessageType, ...] = tuple(
    t
    for t in (
        getattr(discord.MessageType, "new_member", None),
        getattr(discord.MessageType, "member_join", None),
    )
    if t is not None
)


def _is_native_join(message: discord.Message) -> bool:
    return message.type in _NATIVE_JOIN_TYPES


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
    has_id = any(k in lowered or k in fields for k in ("user id:", "userid:", "user id", "userid"))
    has_join = any(
        phrase in lowered
        for phrase in (
            "new member joined",
            "member joined",
            "member join",
            "user joined",
            "joined the server",
        )
    )

    if not (has_user and has_id and has_join):
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
        "date": fields.get("date") or from_regex(r"Date:\s*(.+)"),
        "time": fields.get("time") or from_regex(r"Time:\s*(.+)"),
        "username": username,
        "user_id": user_id,
        "server_name": server_name,
    }


def parse_native_join(message: discord.Message) -> dict | None:
    if not _is_native_join(message):
        return None
    if not message.author:
        return None

    date_str, time_str = _format_timestamp(message.created_at)
    server_name = message.guild.name if message.guild else None

    username = message.author.display_name or str(message.author)
    return {
        "date": date_str,
        "time": time_str,
        "username": username,
        "user_id": str(message.author.id),
        "server_name": server_name,
    }


def build_capture_message(data: dict) -> str:
    """Premium card as markdown (user tokens cannot send embeds on Discord's API)."""
    lines = [
        "🎉 **NEW MEMBER CAPTURED** 🎉",
        f"📅 **Date:** {data.get('date') or 'N/A'}",
        f"⏰ **Time:** {data.get('time') or 'N/A'}",
        f"🆔 **User ID:** {data.get('user_id') or 'N/A'}",
        f"👤 **Username:** `{data.get('username') or 'N/A'}`",
        f"🏠 **Target Server:** {data.get('server_name') or 'N/A'}",
        "",
        "_Tap the username above to copy._",
    ]
    return "\n".join(lines) + "\n\u200b\n" + "─" * 30


def build_startup_message(session_label: str, guild_count: int) -> str:
    return (
        "✅ **Scraper online**\n"
        f"Session **{session_label}** is active.\n"
        f"Monitoring **{guild_count}** server(s). New member captures will appear here."
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
    """One Discord user session → one output group chat."""

    def __init__(self, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_chat_id = target_chat_id
        self._target_channel: discord.abc.Messageable | None = None
        self._seen_ids: set[int] = set()
        self._poll_channels: list[discord.TextChannel] = []
        self._session_label = "client"
        self._captures = 0
        self._messages_seen = 0
        self._monitor_from: datetime | None = None

    @property
    def session_label(self) -> str:
        if self.user:
            return str(self.user)
        return self._session_label

    async def on_ready(self):
        self._monitor_from = datetime.now(timezone.utc)
        self._session_label = str(self.user) if self.user else "client"
        _log(self.session_label, f"Logged in (id: {self.user.id})")
        _log(
            self.session_label,
            f"Live capture window started at {_monitor_from.isoformat()} (only new joins after this).",
        )
        _log(self.session_label, f"Monitoring {len(self.guilds)} server(s).")

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            _log(
                self.session_label,
                f"Output chat: {self._target_channel} (id: {self.target_chat_id})",
            )
            if SEND_STARTUP_PING:
                await self._send_startup_ping()
        except Exception as exc:
            _log(self.session_label, f"Could not open output chat: {exc}")
            return

        await asyncio.sleep(5)
        self._poll_channels = await self._discover_channels()
        warmed, failed = await self._warm_channels(self._poll_channels)
        _log(
            self.session_label,
            f"Channels matched: {len(self._poll_channels)}, warmed: {warmed}, no access: {failed}",
        )
        self.loop.create_task(self._history_poll_loop())
        self.loop.create_task(self._heartbeat_loop())

    async def _send_startup_ping(self) -> None:
        if self._target_channel is None:
            return
        try:
            content = build_startup_message(self.session_label, len(self.guilds))
            await self._target_channel.send(content)
            _log(self.session_label, "Startup message sent.")
        except Exception as exc:
            _log(self.session_label, f"Startup message failed: {exc}")

    async def _guild_text_channels(self, guild: discord.Guild) -> list[discord.TextChannel]:
        try:
            fetched = await guild.fetch_channels()
            return [c for c in fetched if isinstance(c, discord.TextChannel)]
        except Exception:
            return list(guild.text_channels)

    def _channel_matches(self, channel: discord.TextChannel) -> bool:
        name = (channel.name or "").lower()
        return any(keyword in name for keyword in CHANNEL_KEYWORDS)

    async def _discover_channels(self) -> list[discord.TextChannel]:
        found: list[discord.TextChannel] = []
        for guild in self.guilds:
            for channel in await self._guild_text_channels(guild):
                if self._channel_matches(channel):
                    found.append(channel)
        return found[:300]

    async def _warm_channels(self, channels: list[discord.TextChannel]) -> tuple[int, int]:
        warmed = 0
        failed = 0
        for channel in channels[:120]:
            try:
                await channel.history(limit=1).flatten()
                warmed += 1
                await asyncio.sleep(0.2)
            except Exception:
                failed += 1
        return warmed, failed

    async def _history_poll_loop(self) -> None:
        await self.wait_until_ready()
        cycle = 0
        while not self.is_closed():
            cycle += 1
            try:
                await self._poll_channels_once(cycle)
            except Exception as exc:
                _log(self.session_label, f"Poll error: {exc}")
            await asyncio.sleep(HISTORY_POLL_SECONDS)

    async def _poll_channels_once(self, cycle: int) -> None:
        if not self._poll_channels:
            self._poll_channels = await self._discover_channels()

        scanned = 0
        for channel in self._poll_channels:
            try:
                batch: list[discord.Message] = []
                async for message in channel.history(limit=POLL_HISTORY_LIMIT):
                    batch.append(message)
                batch.sort(key=lambda m: m.created_at)
                for message in batch:
                    await self._process_message(message, source="poll")
                scanned += 1
                await asyncio.sleep(0.15)
            except Exception:
                pass

        if cycle % 3 == 0:
            _log(self.session_label, f"Poll cycle {cycle}: scanned {scanned} log channel(s).")

    async def _heartbeat_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(300)
            _log(
                self.session_label,
                f"Heartbeat: {self._messages_seen} messages seen, {self._captures} captures sent.",
            )

    async def on_message(self, message: discord.Message):
        await self._process_message(message, source="live")

    def _is_live_capture(self, message: discord.Message) -> bool:
        if self._monitor_from is None:
            return True
        return _utc(message.created_at) >= self._monitor_from

    def _remember_message(self, message: discord.Message) -> None:
        self._seen_ids.add(message.id)
        if len(self._seen_ids) > 10000:
            drop = len(self._seen_ids) - 8000
            for mid in list(self._seen_ids)[:drop]:
                self._seen_ids.discard(mid)

    async def _process_message(self, message: discord.Message, source: str = "live") -> None:
        if message.id in self._seen_ids:
            return

        if message.author and self.user and message.author.id == self.user.id:
            self._remember_message(message)
            return

        if not self._is_live_capture(message):
            self._remember_message(message)
            return

        self._remember_message(message)
        self._messages_seen += 1
        data, kind = extract_capture(message)
        if data is None:
            return

        guild_name = message.guild.name if message.guild else "DM"
        channel_name = getattr(message.channel, "name", "dm")
        _log(
            self.session_label,
            f"Capture ({kind}) {data.get('username')} @ {guild_name}/#{channel_name} [{source}]",
        )

        channel = self._target_channel
        if channel is None:
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
            except Exception as exc:
                _log(self.session_label, f"Output chat unavailable: {exc}")
                return

        content = build_capture_message(data)
        try:
            sent = await channel.send(content)
            self._captures += 1
            _log(self.session_label, f"Forwarded capture (id: {sent.id}, via {source}).")
        except Exception as exc:
            _log(self.session_label, f"Send failed: {exc}")
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
                sent = await channel.send(content)
                self._captures += 1
                _log(self.session_label, f"Retry send OK (id: {sent.id}).")
            except Exception as retry_exc:
                _log(self.session_label, f"Retry send failed: {retry_exc}")


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("engine", "Starting universal join client...")
    client = UniversalJoinClient(target_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
