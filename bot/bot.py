"""
Option C join scraper — Pikanto production model.

Unprivileged self-bot: reads welcome/log-bot messages in text channels (no admin).
  • Live on_message
  • Light log-channel activation (opens channels so Discord delivers events)
  • Small background poll on log channels only (catches missed live events)

One DISCORD_TOKEN + one CHAT_ID_CLIENT_1 per Render worker / paying customer.

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
POLL_SECONDS = int((os.getenv("POLL_SECONDS") or "45").strip() or 45)
POLL_LIMIT = int((os.getenv("POLL_LIMIT") or "5").strip() or 5)
MAX_LOG_CHANNELS = int((os.getenv("MAX_LOG_CHANNELS") or "120").strip() or 120)

LOG_CHANNEL_KEYWORDS = (
    "welcome", "joins", "join", "gate", "logs", "log", "member", "members",
    "audit", "arrival", "new", "notify", "bot", "general",
)

_NATIVE_JOIN_TYPES: tuple[discord.MessageType, ...] = tuple(
    t
    for t in (
        getattr(discord.MessageType, "new_member", None),
        getattr(discord.MessageType, "member_join", None),
    )
    if t is not None
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _unix(dt: datetime) -> int:
    return int(_utc(dt).timestamp())


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


def parse_log_message(text: str) -> dict | None:
    """Match Smart Tech / welcome-bot join logs (Pikanto-style)."""
    lowered = text.lower()
    if "username:" not in lowered:
        return None
    if "server:" not in lowered and "target server:" not in lowered:
        return None

    has_join = any(
        p in lowered
        for p in (
            "new member joined",
            "member joined",
            "member join",
            "user joined",
            "joined the server",
            "has joined",
        )
    )
    title_join = "join" in lowered and "member" in lowered
    if not (has_join or title_join):
        return None

    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("**", "").replace("`", "")
        value = value.strip().replace("**", "").replace("`", "")
        if key and value:
            fields[key] = value

    def from_regex(pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().replace("**", "").replace("`", "")

    username = fields.get("username") or from_regex(r"Username:\s*(.+)")
    user_id = (
        fields.get("user id")
        or fields.get("userid")
        or from_regex(r"User\s*ID:\s*(\d+)")
    )
    server_name = (
        fields.get("server")
        or fields.get("target server")
        or fields.get("server name")
        or from_regex(r"Server:\s*(.+)")
        or from_regex(r"Target\s+Server:\s*(.+)")
    )

    if not username or not server_name:
        return None

    return {
        "username": username,
        "user_id": user_id or "N/A",
        "server_name": server_name,
    }


def parse_system_join(message: discord.Message) -> dict | None:
    if message.type not in _NATIVE_JOIN_TYPES:
        return None
    if not message.author:
        return None
    return {
        "username": message.author.display_name or str(message.author),
        "user_id": str(message.author.id),
        "server_name": message.guild.name if message.guild else "Unknown",
    }


def extract_capture(message: discord.Message) -> dict | None:
    system = parse_system_join(message)
    if system:
        return system
    return parse_log_message(collect_message_text(message))


def build_alert_message(username: str, user_id: str, server_name: str, ts: int) -> str:
    return (
        "🎉 New Member Joined 🎉\n"
        f"📅 Date: <t:{ts}:D>\n"
        f"⏰ Time: <t:{ts}:t>\n"
        f"🆔 User ID: {user_id}\n"
        f"👤 Username: `{username}`\n"
        f"🏠 Target Server: {server_name}\n"
        "\n"
        "----------------------------------------"
    )


def build_startup_message(session_label: str, ts: int) -> str:
    return (
        "✅ Scraper Online\n"
        f"Session: {session_label} is listening for new joins.\n"
        f"📅 Date: <t:{ts}:D>\n"
        f"⏰ Time: <t:{ts}:t>\n"
        "----------------------------------------"
    )


class PikantoScraper(discord.Client):
    """One paying customer = one token + one output group chat."""

    def __init__(self, output_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_chat_id = output_chat_id
        self._output_channel: discord.abc.Messageable | None = None
        self._ready_once = False
        self._live_after: datetime | None = None
        self._log_channels: list[discord.TextChannel] = []
        self._seen_message_ids: set[int] = set()
        self._recent_joins: set[tuple[str, str]] = set()
        self._send_lock = asyncio.Lock()
        self._captures = 0
        self._messages_seen = 0

    def _channel_is_log(self, channel: discord.TextChannel) -> bool:
        name = (channel.name or "").lower()
        return any(k in name for k in LOG_CHANNEL_KEYWORDS)

    def _discover_log_channels(self) -> list[discord.TextChannel]:
        found: list[discord.TextChannel] = []
        seen: set[int] = set()
        for guild in self.guilds:
            for channel in guild.text_channels:
                if not isinstance(channel, discord.TextChannel):
                    continue
                if channel.id in seen:
                    continue
                if self._channel_is_log(channel):
                    found.append(channel)
                    seen.add(channel.id)
                if len(found) >= MAX_LOG_CHANNELS:
                    return found
        return found

    async def _activate_log_channels(self) -> None:
        try:
            self._log_channels = self._discover_log_channels()
            warmed = 0
            for channel in self._log_channels:
                try:
                    await channel.history(limit=1).flatten()
                    warmed += 1
                    await asyncio.sleep(0.15)
                except Exception:
                    pass
            _log(
                f"[Ready] Log channels: {len(self._log_channels)} matched, "
                f"{warmed} opened for live events."
            )
        except Exception as exc:
            _log(f"[Error] Log channel activation failed: {exc}")

    async def _poll_log_channels(self) -> None:
        if not self._log_channels:
            self._log_channels = self._discover_log_channels()
        for channel in self._log_channels:
            try:
                batch: list[discord.Message] = []
                async for message in channel.history(limit=POLL_LIMIT):
                    batch.append(message)
                batch.sort(key=lambda m: m.created_at)
                for message in batch:
                    await self._handle_message(message, source="poll")
                await asyncio.sleep(0.12)
            except Exception:
                pass

    async def _poll_loop(self) -> None:
        await self.wait_until_ready()
        await asyncio.sleep(8)
        while not self.is_closed():
            try:
                await self._poll_log_channels()
            except Exception as exc:
                _log(f"[Error] Poll loop: {exc}")
            await asyncio.sleep(POLL_SECONDS)

    async def _heartbeat_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(180)
            _log(
                f"[Heartbeat] {self._messages_seen} msgs seen, "
                f"{self._captures} captures, "
                f"{len(self._log_channels)} log channels."
            )

    def _join_key(self, user_id: str, server_name: str) -> tuple[str, str]:
        return (str(user_id), str(server_name).strip().lower())

    def _already_forwarded_join(self, user_id: str, server_name: str) -> bool:
        key = self._join_key(user_id, server_name)
        if key in self._recent_joins:
            return True
        self._recent_joins.add(key)
        if len(self._recent_joins) > 500:
            self._recent_joins = set(list(self._recent_joins)[-300:])
        return False

    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        self._live_after = datetime.now(timezone.utc)

        _log(f"[Success] Logged in as {self.user}")
        _log(f"[Ready] Monitoring {len(self.guilds)} server(s) (live + log channels).")

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
                ts = _unix(datetime.now(timezone.utc))
                async with self._send_lock:
                    await self._output_channel.send(
                        build_startup_message(str(self.user), ts)
                    )
                _log("[Ready] Startup message sent.")
            except Exception as exc:
                _log(f"[Error] Startup failed: {exc}")

        self.loop.create_task(self._activate_log_channels())
        self.loop.create_task(self._poll_loop())
        self.loop.create_task(self._heartbeat_loop())

    async def _forward(
        self,
        *,
        username: str,
        user_id: str,
        server_name: str,
        ts: int,
        source: str,
    ) -> None:
        async with self._send_lock:
            if self._already_forwarded_join(user_id, server_name):
                _log(f"[Skip] Duplicate join: {username} @ {server_name}")
                return

            channel = self._output_channel
            if channel is None:
                try:
                    channel = await self.fetch_channel(self.output_chat_id)
                    self._output_channel = channel
                except Exception as exc:
                    _log(f"[Error] Output chat unavailable: {exc}")
                    return

            try:
                msg = await channel.send(
                    build_alert_message(username, user_id, server_name, ts)
                )
                self._captures += 1
                _log(f"[Sent] {username} → {server_name} via {source} (msg {msg.id})")
            except Exception as exc:
                self._recent_joins.discard(self._join_key(user_id, server_name))
                _log(f"[Error] Send failed: {exc}")

    async def _handle_message(self, message: discord.Message, source: str) -> None:
        if self._live_after is None:
            return
        if message.id in self._seen_message_ids:
            return
        self._seen_message_ids.add(message.id)
        if len(self._seen_message_ids) > 10000:
            self._seen_message_ids = set(list(self._seen_message_ids)[-6000:])

        if message.author and self.user and message.author.id == self.user.id:
            return
        if _utc(message.created_at) < self._live_after:
            return

        self._messages_seen += 1
        data = extract_capture(message)
        if data is None:
            return

        capture_source = (
            "system_join" if message.type in _NATIVE_JOIN_TYPES else "log_text"
        )
        await self._forward(
            username=data["username"],
            user_id=str(data["user_id"]),
            server_name=data["server_name"],
            ts=_unix(message.created_at),
            source=f"{capture_source}/{source}",
        )

    async def on_message(self, message: discord.Message):
        await self._handle_message(message, source="live")


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("[Engine] Starting Pikanto-style join scraper...")
    client = PikantoScraper(output_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
