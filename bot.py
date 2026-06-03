"""
Discord self-bot that watches for third-party log-bot "New Member Joined!"
messages, extracts fields, and forwards them to the correct group chat.

Multiple accounts run together. Any account may *see* a join log; the bot picks
which group chat should receive it based on which account(s) are in that server.
If several accounts share a server, Clients 2–4 take priority over Client 1 so
Pikanto does not steal joins meant for Stevo / Emenite.

Optional override: MONITOR_SERVERS_CLIENT_N=Server A,Server B on Render.

WARNING: Self-botting violates Discord ToS. Use at your own risk.
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


# ---------------------------------------------------------------------------
# LIBRARY COMPATIBILITY PATCH
# ---------------------------------------------------------------------------
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


def load_monitor_servers(client_index: int) -> list[str]:
    raw = (os.getenv(f"MONITOR_SERVERS_CLIENT_{client_index}") or "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def load_accounts():
    accounts = []
    for i in range(1, 21):
        token = (os.getenv(f"TOKEN_CLIENT_{i}") or "").strip()
        if not token:
            continue

        chat_id_raw = (os.getenv(f"CHAT_ID_CLIENT_{i}") or "").strip()
        try:
            chat_id = int(chat_id_raw) if chat_id_raw else 0
        except ValueError:
            raise SystemExit(
                f"CHAT_ID_CLIENT_{i} must be a numeric Discord channel ID, got: {chat_id_raw!r}"
            )

        accounts.append(
            {
                "index": i,
                "name": (os.getenv(f"NAME_CLIENT_{i}") or f"Client {i}").strip(),
                "token": token,
                "chat_id": chat_id,
                "monitor_servers": load_monitor_servers(i),
            }
        )
    return accounts


ACCOUNTS = load_accounts()


FIELD_STYLE = [
    ("Date",          "date",        "📅", C.CYAN),
    ("Time",          "time",        "⏰", C.CYAN),
    ("Username",      "username",    "👤", C.GREEN),
    ("Target Server", "server_name", "🏠", C.PURPLE),
]


def process_extracted_data(data: dict, client_name: str = ""):
    prefix = f"[{client_name}] " if client_name else ""
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
    bot = f"{C.GOLD}╚{'═' * (inner_width + 2)}╝{C.RESET}"
    bar = f"{C.GOLD}║{C.RESET}"
    title_pad = inner_width - title_cells
    left = title_pad // 2
    right = title_pad - left

    print()
    if prefix:
        print(f"{prefix}capture detected", flush=True)
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
    print(bot)
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

    return {
        "date": clean(re.search(r"Date:\s*(.+)", full_text, re.IGNORECASE)),
        "time": clean(re.search(r"Time:\s*(.+)", full_text, re.IGNORECASE)),
        "username": clean(re.search(r"Username:\s*(.+)", full_text, re.IGNORECASE)),
        "server_name": clean(re.search(r"Server:\s*(.+)", full_text, re.IGNORECASE)),
        "user_id": clean(re.search(r"User ID:\s*(.+)", full_text, re.IGNORECASE)),
    }


def server_name_matches_guild(server_name: str, guild_name: str) -> bool:
    a = server_name.lower().strip()
    b = guild_name.lower().strip()
    return a in b or b in a


# ---------------------------------------------------------------------------
# SMART ROUTER
# ---------------------------------------------------------------------------

class CaptureRouter:
    """Pick the right group chat for a capture based on server membership."""

    def __init__(self):
        self._clients: dict[int, "ScraperClient"] = {}
        self._lock = asyncio.Lock()
        self._delivered: dict[str, set[int]] = {}
        self._pending: list[tuple["ScraperClient", dict]] = []

    def register(self, client: "ScraperClient") -> None:
        self._clients[client.client_index] = client
        asyncio.create_task(self._flush_pending())

    async def _flush_pending(self) -> None:
        await asyncio.sleep(0.5)
        pending = list(self._pending)
        self._pending.clear()
        for source, data in pending:
            await self.dispatch(source, data)

    def _explicit_owner(self, server_name: str) -> dict | None:
        lowered = server_name.lower()
        # Check Client 4 → 3 → 2 → 1 so Pikanto never wins a manual route.
        for account in sorted(ACCOUNTS, key=lambda a: a["index"], reverse=True):
            for pattern in account["monitor_servers"]:
                if pattern.lower() in lowered:
                    return account
        return None

    def _membership_owners(self, server_name: str) -> list[dict]:
        owners = []
        for account in ACCOUNTS:
            client = self._clients.get(account["index"])
            if client is None:
                continue
            for guild in client.guilds:
                if server_name_matches_guild(server_name, guild.name):
                    owners.append(account)
                    break
        return owners

    def resolve_owner(self, server_name: str, source_index: int) -> dict | None:
        if not server_name:
            return next((a for a in ACCOUNTS if a["index"] == source_index), None)

        explicit = self._explicit_owner(server_name)
        if explicit:
            return explicit

        members = self._membership_owners(server_name)
        if not members:
            return next((a for a in ACCOUNTS if a["index"] == source_index), None)

        if len(members) == 1:
            return members[0]

        # Shared server: prefer Client 4 > 3 > 2 > 1 so Pikanto does not take Stevo/Emenite joins.
        return max(members, key=lambda a: a["index"])

    async def dispatch(self, source: "ScraperClient", data: dict) -> None:
        server = data.get("server_name") or ""
        username = data.get("username") or "unknown"
        dedup_key = f"{data.get('user_id')}:{server}:{username}"

        owner_account = self.resolve_owner(server, source.client_index)
        if owner_account is None:
            print(f"[{source.name}] No owner for server {server!r}.", flush=True)
            return

        owner = self._clients.get(owner_account["index"])
        chat_id = owner_account["chat_id"]
        label = owner_account["name"]

        if owner is None:
            print(
                f"[{label}] Waiting for {username} ({server}) — owner not online yet.",
                flush=True,
            )
            self._pending.append((source, data))
            return

        async with self._lock:
            if chat_id in self._delivered.get(dedup_key, set()):
                return

        try:
            await owner.send_capture(data)
        except Exception as exc:
            print(f"[{label}] Failed to send to chat {chat_id}: {exc}", flush=True)
            return

        async with self._lock:
            self._delivered.setdefault(dedup_key, set()).add(chat_id)
            if len(self._delivered) > 500:
                self._delivered.clear()

        if source.client_index != owner.client_index:
            print(
                f"[{label}] Forwarded {username} ({server}) — routed from {source.name}.",
                flush=True,
            )
        else:
            print(f"[{label}] Forwarded capture for {username}.", flush=True)


ROUTER = CaptureRouter()


class ScraperClient(discord.Client):
    def __init__(
        self,
        name: str,
        client_index: int,
        target_chat_id: int,
        monitor_servers: list[str],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.name = name
        self.client_index = client_index
        self.target_chat_id = target_chat_id
        self.monitor_servers = monitor_servers
        self._target_channel = None

    async def send_capture(self, data: dict) -> None:
        channel = self._target_channel
        if channel is None:
            channel = await self.fetch_channel(self.target_chat_id)
            self._target_channel = channel
        await channel.send(build_message(data))

    async def on_ready(self):
        print(f"[{self.name}] Logged in as {self.user} (id: {self.user.id})", flush=True)
        print(f"[{self.name}] In {len(self.guilds)} server(s).", flush=True)

        guild_names = sorted(g.name for g in self.guilds)
        preview = ", ".join(guild_names[:10])
        if len(guild_names) > 10:
            preview += f", ... (+{len(guild_names) - 10} more)"
        print(f"[{self.name}] Servers: {preview}", flush=True)

        if not self.target_chat_id:
            return

        try:
            self._target_channel = await self.fetch_channel(self.target_chat_id)
            ROUTER.register(self)
            print(f"[{self.name}] Group chat: {self._target_channel}", flush=True)
            if self.monitor_servers:
                print(
                    f"[{self.name}] Manual routes: {', '.join(self.monitor_servers)}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[{self.name}] Could not open chat {self.target_chat_id}: {exc}", flush=True)

    async def on_message(self, message):
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

        data = parse_join_log("\n".join(parts))
        if data is None:
            return

        process_extracted_data(data, client_name=self.name)
        await ROUTER.dispatch(self, data)


async def run_client(account: dict):
    client = ScraperClient(
        name=account["name"],
        client_index=account["index"],
        target_chat_id=account["chat_id"],
        monitor_servers=account["monitor_servers"],
    )
    try:
        await client.start(account["token"])
    except Exception as exc:
        print(f"[{account['name']}] Stopped: {exc}", flush=True)


async def main():
    print("Starting scraper (smart routing by server membership)...", flush=True)

    if not ACCOUNTS:
        raise SystemExit("No accounts found. Set TOKEN_CLIENT_1 / CHAT_ID_CLIENT_1, etc.")

    tasks = []
    # Start Clients 4→1 so Stevo/Emenite accounts are online before Pikanto captures.
    for account in sorted(ACCOUNTS, key=lambda a: a["index"], reverse=True):
        if not account["chat_id"]:
            raise SystemExit(
                f"CHAT_ID_CLIENT_{account['index']} missing for {account['name']}."
            )
        print(
            f"[{account['name']}] Connecting → chat {account['chat_id']}...",
            flush=True,
        )
        tasks.append(asyncio.create_task(run_client(account)))

    print(
        "Routing: shared servers go to highest client # (4>3>2>1). "
        "Override with MONITOR_SERVERS_CLIENT_N on Render if needed.",
        flush=True,
    )
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
