"""
Native join listener (Option C) — Smart Tech style.

Listens for Discord's on_member_join event only (no channel reading or regex).
Forwards a capture card to CHAT_ID_CLIENT_1 when someone joins any visible server.

WARNING: Automating a user account (self-botting) violates Discord's ToS.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.http import handle_message_parameters
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

WAT = ZoneInfo("Africa/Lagos")
CARD_COLOR = 0x57F287


def _log(msg: str) -> None:
    print(msg, flush=True)


def wat_now() -> tuple[str, str]:
    now = datetime.now(WAT)
    return now.strftime("%B %d, %Y"), now.strftime("%I:%M:%S %p").lstrip("0")


def build_capture_embed(
    username: str,
    user_id: int,
    server_name: str,
    date_str: str,
    time_str: str,
) -> discord.Embed:
    embed = discord.Embed(title="🎉 New Member Joined!", color=CARD_COLOR)
    embed.add_field(name="📅 Date", value=date_str, inline=False)
    embed.add_field(name="🕒 Time", value=time_str, inline=False)
    embed.add_field(name="👤 Username", value=f"`{username}`", inline=False)
    embed.add_field(name="🆔 User ID", value=str(user_id), inline=False)
    embed.add_field(name="🏠 Server", value=server_name, inline=False)
    embed.set_footer(text="Tap username to copy")
    return embed


def build_capture_message(
    username: str,
    user_id: int,
    server_name: str,
    date_str: str,
    time_str: str,
) -> str:
    """Markdown fallback — user tokens cannot send embeds via the API."""
    return (
        f"📅 **Date:** {date_str}\n"
        f"🕒 **Time:** {time_str}\n"
        f"👤 **Username:** `{username}`\n"
        f"🆔 **User ID:** {user_id}\n"
        f"🏠 **Server:** {server_name}\n"
        f"🎉 **New Member Joined!**"
    )


async def send_card(
    channel: discord.abc.Messageable,
    embed: discord.Embed,
    *,
    fallback_text: str | None = None,
) -> discord.Message:
    """
    Dispatch via HTTP payload (embed serialized with .to_dict() internally).
    Falls back to markdown if user-token embeds are rejected (API 50006).
    """
    target = await channel._get_channel()
    state = channel._state
    try:
        with handle_message_parameters(embed=embed) as params:
            data = await state.http.send_message(target.id, params=params)
        return state.create_message(channel=target, data=data)
    except Exception:
        if fallback_text:
            return await channel.send(fallback_text)
        raise


class NativeJoinClient(discord.Client):
    def __init__(self, output_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_chat_id = output_chat_id
        self._output_channel: discord.abc.Messageable | None = None
        self._ready_once = False

    async def on_ready(self):
        if self._ready_once:
            return
        self._ready_once = True

        _log(f"[Success] Logged in as {self.user}")

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
            date_str, time_str = wat_now()
            ping = discord.Embed(
                title="✅ Scraper online",
                description=(
                    f"Session **{self.user}** is listening for joins.\n"
                    f"📅 {date_str} · 🕒 {time_str} (WAT)"
                ),
                color=CARD_COLOR,
            )
            try:
                await send_card(self._output_channel, ping)
                _log("[Ready] Startup card sent.")
            except Exception as exc:
                _log(f"[Error] Startup card failed: {exc}")

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        date_str, time_str = wat_now()
        username = member.name
        user_id = member.id
        server_name = member.guild.name if member.guild else "Unknown"

        _log(
            f"[Join] {username} ({user_id}) → {server_name} @ {time_str} WAT"
        )

        channel = self._output_channel
        if channel is None:
            try:
                channel = await self.fetch_channel(self.output_chat_id)
                self._output_channel = channel
            except Exception as exc:
                _log(f"[Error] Output chat unavailable: {exc}")
                return

        embed = build_capture_embed(username, user_id, server_name, date_str, time_str)
        fallback = build_capture_message(
            username, user_id, server_name, date_str, time_str
        )
        try:
            msg = await send_card(channel, embed, fallback_text=fallback)
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
