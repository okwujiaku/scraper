"""
Option C dual-trigger join engine.

One user token per deployment. Captures joins via:
  1) Live log-bot messages in text channels (on_message + regex)
  2) Native server gate events (on_member_join)

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
MAX_JOIN_AGE_SECONDS = int((os.getenv("MAX_JOIN_AGE_SECONDS") or "120").strip() or 120)

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
    """Extract join fields from log-bot text (Username:, Server:, etc.)."""
    lowered = text.lower()
    if "username:" not in lowered or "server:" not in lowered:
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


def build_alert_message(username: str, user_id: str, server_name: str, ts: int) -> str:
    """Single text block — Discord renders date/time per viewer device."""
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
        f"Session **{session_label}** is listening for new joins.\n"
        f"📅 Date: <t:{ts}:D>\n"
        f"⏰ Time: <t:{ts}:t>\n"
        "\n"
        "----------------------------------------"
    )


def is_fresh_member_join(member: discord.Member, live_after: datetime) -> bool:
    if member.joined_at is None:
        return False
    joined = _utc(member.joined_at)
    if joined < live_after:
        return False
    age = (datetime.now(timezone.utc) - joined).total_seconds()
    return age <= MAX_JOIN_AGE_SECONDS


class DualTriggerClient(discord.Client):
    def __init__(self, output_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_chat_id = output_chat_id
        self._output_channel: discord.abc.Messageable | None = None
        self._ready_once = False
        self._live_after: datetime | None = None
        self._recent: set[tuple[str, str]] = set()
        self._send_lock = asyncio.Lock()

    def _dedup_key(self, user_id: str, server_name: str) -> tuple[str, str]:
        return (str(user_id), str(server_name).strip().lower())

    def _already_sent(self, user_id: str, server_name: str) -> bool:
        key = self._dedup_key(user_id, server_name)
        if key in self._recent:
            return True
        self._recent.add(key)
        if len(self._recent) > 500:
            self._recent = set(list(self._recent)[-300:])
        return False

    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True
        self._live_after = datetime.now(timezone.utc)

        _log(f"[Success] Logged in as {self.user}")
        _log(f"[Ready] Monitoring {len(self.guilds)} server(s) (live only).")

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
            if self._already_sent(user_id, server_name):
                _log(f"[Skip] Duplicate ({source}): {username} @ {server_name}")
                return

            channel = self._output_channel
            if channel is None:
                try:
                    channel = await self.fetch_channel(self.output_chat_id)
                    self._output_channel = channel
                except Exception as exc:
                    _log(f"[Error] Output chat unavailable: {exc}")
                    return

            content = build_alert_message(username, user_id, server_name, ts)
            try:
                msg = await channel.send(content)
                _log(f"[Sent] {username} → {server_name} via {source} (msg {msg.id})")
            except Exception as exc:
                self._recent.discard(self._dedup_key(user_id, server_name))
                _log(f"[Error] Send failed ({source}): {exc}")

    async def on_message(self, message: discord.Message):
        if self._live_after is None:
            return
        if message.author and self.user and message.author.id == self.user.id:
            return
        if _utc(message.created_at) < self._live_after:
            return

        if message.type in _NATIVE_JOIN_TYPES:
            return

        data = parse_log_message(collect_message_text(message))
        if data is None:
            return

        ts = _unix(message.created_at)
        await self._forward(
            username=data["username"],
            user_id=str(data["user_id"]),
            server_name=data["server_name"],
            ts=ts,
            source="message",
        )

    async def on_member_join(self, member: discord.Member):
        if member.bot or self._live_after is None:
            return
        if not is_fresh_member_join(member, self._live_after):
            return

        ts = _unix(member.joined_at or datetime.now(timezone.utc))
        await self._forward(
            username=member.name,
            user_id=str(member.id),
            server_name=member.guild.name if member.guild else "Unknown",
            ts=ts,
            source="member_join",
        )


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("[Engine] Starting dual-trigger join engine...")
    client = DualTriggerClient(output_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
