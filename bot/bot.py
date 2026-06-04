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


_JOIN_PHRASES = (
    "new member joined",
    "member joined!",
    "member joined",
    "member join",
    "user joined",
    "has joined",
    "joined the server",
    "welcome to the server",
)

_FIELD_LINE_LABELS = frozenset({
    "username", "user", "member", "user id", "userid", "discord id",
    "member id", "server", "target server", "server name", "guild",
    "date", "time",
})


def _normalize_field_lines(text: str) -> str:
    """Username\\nvalue pairs (embed flatten bug) -> Username: value."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i].strip().replace("**", "").replace("`", "")
        key = raw.rstrip(":").lower()
        if key in _FIELD_LINE_LABELS and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            nxt_key = nxt.rstrip(":").lower()
            if nxt and nxt_key not in _FIELD_LINE_LABELS:
                label = raw.rstrip(":")
                out.append(f"{label}: {nxt}")
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _has_join_phrase(text: str) -> bool:
    lowered = text.lower()
    if any(p in lowered for p in _JOIN_PHRASES):
        return True
    if re.search(r"joined\s*<t:\d+", lowered):
        return True
    if "welcome" in lowered and "server" in lowered:
        return True
    return "join" in lowered and "member" in lowered


def _has_user_markers(text: str) -> bool:
    lowered = text.lower()
    if "username:" in lowered or "user:" in lowered:
        return True
    if re.search(r"member\s*[:：]\s*(?!<?@)", text, re.IGNORECASE):
        return True
    return bool(re.search(r"username\s*[:：]", text, re.IGNORECASE))


def _has_id_markers(text: str) -> bool:
    lowered = text.lower()
    if any(m in lowered for m in ("user id:", "userid:", "discord id:", "member id:")):
        return True
    if re.search(r"member\s*[:：]\s*<?@!?\d{17,20}>?", text, re.IGNORECASE):
        return True
    return bool(re.search(r"<?@!?\d{17,20}>?", text))


def is_join_log(text: str) -> bool:
    normalized = _normalize_field_lines(text)
    return (
        _has_join_phrase(normalized)
        and _has_user_markers(normalized)
        and _has_id_markers(normalized)
    )


def _clean_field(match) -> str | None:
    if not match:
        return None
    return match.group(1).strip().replace("**", "").replace("`", "").strip()


def _snowflake_from(value: str) -> str | None:
    m = re.search(r"(\d{17,20})", value or "")
    return m.group(1) if m else None


def _embed_field_map(message: discord.Message) -> dict[str, str]:
    aliases = {
        "username": "username",
        "user": "username",
        "member": "username",
        "user id": "user_id",
        "userid": "user_id",
        "discord id": "user_id",
        "member id": "user_id",
        "server": "server_name",
        "target server": "server_name",
        "server name": "server_name",
        "guild": "server_name",
        "guild name": "server_name",
    }
    found: dict[str, str] = {}
    for embed in message.embeds:
        for field in embed.fields:
            key = re.sub(r"[^a-z0-9]+", " ", (field.name or "").lower()).strip()
            canon = aliases.get(key, key)
            value = (field.value or "").strip().replace("**", "").replace("`", "")
            if canon == "username" and _snowflake_from(value) and not found.get("user_id"):
                found["user_id"] = _snowflake_from(value) or value
                continue
            if canon and value:
                found[canon] = value
    return found


def _parse_from_field_map(field_map: dict[str, str], full_text: str) -> dict | None:
    text = _normalize_field_lines(full_text)

    username = field_map.get("username")
    if username and _snowflake_from(username) and not field_map.get("user_id"):
        field_map = dict(field_map)
        field_map["user_id"] = _snowflake_from(username)
        username = None

    if not username:
        for pattern in (
            r"Username\s*[:：]\s*(.+)",
            r"User\s*[:：]\s*(.+)",
            r"Member\s*[:：]\s*(.+)",
        ):
            candidate = _clean_field(re.search(pattern, text, re.IGNORECASE))
            if candidate and not _snowflake_from(candidate):
                username = candidate
                break

    user_id = field_map.get("user_id")
    if not user_id:
        for pattern in (
            r"User\s*ID\s*[:：]\s*(.+)",
            r"Userid\s*[:：]\s*(.+)",
            r"Discord\s*ID\s*[:：]\s*(.+)",
            r"Member\s*ID\s*[:：]\s*(.+)",
            r"Member\s*[:：]\s*(.+)",
        ):
            candidate = _clean_field(re.search(pattern, text, re.IGNORECASE))
            if candidate:
                user_id = _snowflake_from(candidate) or candidate
                break
    if not user_id:
        user_id = _snowflake_from(text)

    server_name = (
        field_map.get("server_name")
        or _clean_field(re.search(r"Target\s+Server\s*[:：]\s*(.+)", text, re.IGNORECASE))
        or _clean_field(re.search(r"Server\s*Name\s*[:：]\s*(.+)", text, re.IGNORECASE))
        or _clean_field(re.search(r"Server\s*[:：]\s*(.+)", text, re.IGNORECASE))
        or _clean_field(re.search(r"Guild\s*[:：]\s*(.+)", text, re.IGNORECASE))
    )

    if not username:
        return None

    return {
        "date": _clean_field(re.search(r"Date\s*[:：]\s*(.+)", text, re.IGNORECASE)),
        "time": _clean_field(re.search(r"Time\s*[:：]\s*(.+)", text, re.IGNORECASE)),
        "username": username,
        "server_name": server_name or "Unknown",
        "user_id": user_id or "N/A",
    }


def parse_join_log_message(message: discord.Message) -> dict | None:
    text = _normalize_field_lines(collect_message_text(message))
    field_map = _embed_field_map(message)

    if message.embeds and field_map.get("username") and _has_join_phrase(text):
        data = _parse_from_field_map(field_map, text)
        if data:
            return data

    if not is_join_log(text):
        return None
    return _parse_from_field_map(field_map, text)


def parse_join_log(full_text: str) -> dict | None:
    text = _normalize_field_lines(full_text)
    if not is_join_log(text):
        return None
    return _parse_from_field_map({}, text)


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
        if message.author and self.user and message.author.id == self.user.id:
            return

        data = parse_join_log_message(message)
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
