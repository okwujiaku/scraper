"""
Option C text-channel join scraper (unprivileged self-bot).

Passive on_message only — no admin permissions, no on_member_join, no channel scans.
Captures log-bot text (Username:, Server:) and native system join messages in channels.

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


def parse_system_join(message: discord.Message) -> dict | None:
    if message.type not in _NATIVE_JOIN_TYPES:
        return None
    if not message.author:
        return None

    server_name = message.guild.name if message.guild else "Unknown"
    return {
        "username": message.author.display_name or str(message.author),
        "user_id": str(message.author.id),
        "server_name": server_name,
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


class TextChannelScraper(discord.Client):
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

    def _mark_sent(self, user_id: str, server_name: str) -> bool:
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
        _log(f"[Ready] Monitoring {len(self.guilds)} server(s) — passive text only.")

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
            if self._mark_sent(user_id, server_name):
                _log(f"[Skip] Duplicate: {username} @ {server_name}")
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
                _log(f"[Sent] {username} → {server_name} via {source} (msg {msg.id})")
            except Exception as exc:
                self._recent.discard(self._dedup_key(user_id, server_name))
                _log(f"[Error] Send failed: {exc}")

    async def on_message(self, message: discord.Message):
        if self._live_after is None:
            return
        if message.author and self.user and message.author.id == self.user.id:
            return
        if _utc(message.created_at) < self._live_after:
            return

        data = extract_capture(message)
        if data is None:
            return

        source = "system_join" if message.type in _NATIVE_JOIN_TYPES else "log_text"
        ts = _unix(message.created_at)

        await self._forward(
            username=data["username"],
            user_id=str(data["user_id"]),
            server_name=data["server_name"],
            ts=ts,
            source=source,
        )


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    if not CHAT_ID:
        raise SystemExit("CHAT_ID_CLIENT_1 is not set.")

    _log("[Engine] Starting text-channel join scraper...")
    client = TextChannelScraper(output_chat_id=CHAT_ID)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
