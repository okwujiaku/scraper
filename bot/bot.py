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
SEND_STARTUP_PING = (os.getenv("SEND_STARTUP_PING") or "true").strip().lower() in (
    "1", "true", "yes", "on",
)
# Poll likely log channels every N seconds (Discord often skips live events until a channel is opened).
HISTORY_POLL_SECONDS = int((os.getenv("HISTORY_POLL_SECONDS") or "90").strip() or 90)
LOG_CHANNEL_KEYWORDS = tuple(
    k.strip().lower()
    for k in (
        os.getenv("LOG_CHANNEL_KEYWORDS")
        or "log,join,welcome,audit,member,members,new,arrival,bot,notify,record,staff,mod"
    ).split(",")
    if k.strip()
)


FIELD_STYLE = [
    ("Date",          "date",        "📅", C.CYAN),
    ("Time",          "time",        "⏰", C.CYAN),
    ("Username",      "username",    "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict, source: str = ""):
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
    bot_line = f"{C.GOLD}╚{'═' * (inner_width + 2)}╝{C.RESET}"
    bar = f"{C.GOLD}║{C.RESET}"
    title_pad = inner_width - title_cells
    left = title_pad // 2
    right = title_pad - left

    print()
    extra = f" ({source})" if source else ""
    print(f"[{CLIENT_NAME}] capture detected{extra}", flush=True)
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
            parts.append(field.name or "")
            parts.append(field.value or "")
    return "\n".join(parts)


def _field_map(text: str) -> dict[str, str]:
    """Build a lowercase key -> value map from 'Label: value' lines and embed-style fields."""
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


def is_join_log(text: str) -> bool:
    lowered = text.lower()
    fields = _field_map(text)

    has_user = (
        "username:" in lowered
        or "username" in fields
        or fields.get("user")
    )
    has_id = (
        "user id:" in lowered
        or "userid:" in lowered
        or "user id" in fields
        or "userid" in fields
        or "id" in fields
    )
    has_join = any(
        phrase in lowered
        for phrase in (
            "new member joined",
            "member joined!",
            "member joined",
            "new member join",
            "user joined",
            "member join",
            "joined the server",
            "new member",
        )
    )
    # Accept logs that have user + id even if join phrase is only in embed title.
    title_join = "join" in lowered and "member" in lowered
    return has_user and has_id and (has_join or title_join)


def parse_join_log(full_text: str) -> dict | None:
    if not is_join_log(full_text):
        return None

    fields = _field_map(full_text)

    def from_regex(pattern: str):
        match = re.search(pattern, full_text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().replace("**", "").replace("`", "").strip()

    username = (
        fields.get("username")
        or fields.get("user")
        or from_regex(r"Username:\s*(.+)")
    )
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
        "server_name": server_name,
        "user_id": user_id,
    }


class ScraperClient(discord.Client):
    def __init__(self, target_chat_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_chat_id = target_chat_id
        self._target_channel = None
        self._seen_message_ids: set[int] = set()
        self._poll_channels: list[discord.TextChannel] = []
        self._messages_seen = 0
        self._captures_sent = 0
        self._poll_cycle = 0

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

        # Guild channel lists are often empty for a few seconds right after READY.
        await asyncio.sleep(5)
        self._poll_channels = await self._discover_log_channels()
        warmed, warm_failed = await self._warm_channels(self._poll_channels)
        print(
            f"[{CLIENT_NAME}] Log channels: {len(self._poll_channels)} matched, "
            f"{warmed} warmed, {warm_failed} no access.",
            flush=True,
        )
        print(
            f"[{CLIENT_NAME}] History poll every {HISTORY_POLL_SECONDS}s "
            f"(log channels + all readable channels).",
            flush=True,
        )
        self.loop.create_task(self._history_poll_loop())
        self.loop.create_task(self._heartbeat_loop())

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

    async def _guild_text_channels(self, guild: discord.Guild) -> list[discord.TextChannel]:
        channels: list[discord.TextChannel] = []
        try:
            async for channel in guild.fetch_channels():
                if isinstance(channel, discord.TextChannel):
                    channels.append(channel)
        except Exception:
            channels = list(guild.text_channels)
        return channels

    async def _iter_text_channels(self):
        for guild in self.guilds:
            for channel in await self._guild_text_channels(guild):
                yield channel

    async def _discover_log_channels(self) -> list[discord.TextChannel]:
        channels: list[discord.TextChannel] = []
        async for channel in self._iter_text_channels():
            name = (channel.name or "").lower()
            if any(keyword in name for keyword in LOG_CHANNEL_KEYWORDS):
                channels.append(channel)
        return channels[:300]

    async def _warm_channels(self, channels: list[discord.TextChannel]) -> tuple[int, int]:
        """Open channels so Discord delivers live MESSAGE_CREATE events."""
        warmed = 0
        failed = 0
        for channel in channels[:120]:
            try:
                await channel.history(limit=1).flatten()
                warmed += 1
                await asyncio.sleep(0.25)
            except Exception:
                failed += 1
        return warmed, failed

    async def _heartbeat_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(300)
            print(
                f"[{CLIENT_NAME}] Heartbeat: {self._messages_seen} messages seen, "
                f"{self._captures_sent} captures sent.",
                flush=True,
            )

    async def _history_poll_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._poll_log_channels()
            except Exception as exc:
                print(f"[{CLIENT_NAME}] History poll error: {exc}", flush=True)
            await asyncio.sleep(HISTORY_POLL_SECONDS)

    async def _poll_log_channels(self) -> None:
        self._poll_cycle += 1
        if not self._poll_channels:
            self._poll_channels = await self._discover_log_channels()

        polled_ok = 0
        for channel in self._poll_channels:
            try:
                async for message in channel.history(limit=10):
                    await self._handle_message(message, source="poll")
                polled_ok += 1
                await asyncio.sleep(0.2)
            except Exception:
                pass

        # Also scan readable channels in a rotating slice of guilds (join logs may
        # be in channels without "log" in the name).
        guilds = list(self.guilds)
        if guilds:
            start = (self._poll_cycle * 5) % len(guilds)
            batch = guilds[start : start + 8]
            for guild in batch:
                count = 0
                for channel in await self._guild_text_channels(guild):
                    try:
                        async for message in channel.history(limit=5):
                            await self._handle_message(message, source="scan")
                        polled_ok += 1
                        count += 1
                        await asyncio.sleep(0.15)
                    except Exception:
                        pass
                    if count >= 12:
                        break

        if self._poll_cycle % 3 == 0:
            print(
                f"[{CLIENT_NAME}] Poll cycle {self._poll_cycle}: "
                f"{polled_ok} channel(s) scanned.",
                flush=True,
            )

    async def _handle_message(self, message: discord.Message, source: str = "live") -> None:
        if message.id in self._seen_message_ids:
            return
        self._seen_message_ids.add(message.id)
        if len(self._seen_message_ids) > 5000:
            self._seen_message_ids.clear()

        if message.author and message.author.id == self.user.id:
            return

        self._messages_seen += 1
        full_text = collect_message_text(message)
        data = parse_join_log(full_text)
        if data is None:
            return

        guild_name = message.guild.name if message.guild else "DM"
        channel_name = getattr(message.channel, "name", "?")
        process_extracted_data(data, source=f"{guild_name} / #{channel_name} / {source}")

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
            self._captures_sent += 1
            print(
                f"[{CLIENT_NAME}] Forwarded {data.get('username') or 'unknown'} "
                f"(msg {msg.id}, via {source}).",
                flush=True,
            )
        except Exception as exc:
            print(f"[{CLIENT_NAME}] Send failed: {exc}", flush=True)
            try:
                channel = await self.fetch_channel(self.target_chat_id)
                self._target_channel = channel
                msg = await channel.send(build_message(data))
                self._captures_sent += 1
                print(f"[{CLIENT_NAME}] Retry send OK (msg {msg.id}).", flush=True)
            except Exception as retry_exc:
                print(f"[{CLIENT_NAME}] Retry send failed: {retry_exc}", flush=True)

    async def on_message(self, message):
        await self._handle_message(message, source="live")


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
