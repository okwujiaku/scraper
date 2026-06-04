"""Run local parser matrix: python test_parser.py

Tests the same is_join_log / parse_join_log used on Render for Pikanto vs
Stevo-shaped join messages (plain text + embed flattening via collect_message_text).
"""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bot", Path(__file__).parent / "bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class FakeField:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeEmbed:
    def __init__(self, title="", description="", fields=None, author=None, footer=None):
        self.title = title
        self.description = description
        self.fields = fields or []
        self.author = author
        self.footer = footer


class FakeAuthor:
    def __init__(self, name):
        self.name = name


class FakeMessage:
    def __init__(self, content="", embeds=None):
        self.content = content
        self.embeds = embeds or []


def flatten(content="", embeds=None):
    return bot.collect_message_text(
        FakeMessage(content=content, embeds=embeds or [])
    )


def gate_fail_reason(text: str) -> str:
    normalized = bot._normalize_field_lines(text)
    missing = []
    if not bot._has_user_markers(normalized):
        missing.append("username/user/member marker")
    if not bot._has_id_markers(normalized):
        missing.append("user id marker")
    if not bot._has_join_phrase(normalized):
        missing.append("join phrase")
    return ", ".join(missing) if missing else "parse extraction failed"


def run_sample(label: str, text: str) -> dict:
    data = bot.parse_join_log(text)
    ok = bot.is_join_log(text)
    return {
        "label": label,
        "is_join_log": ok,
        "parsed": data is not None,
        "reason": "" if data else gate_fail_reason(text),
        "data": data,
    }


def run_embed_sample(label: str, content="", title="", description="", fields=None):
    embeds = [FakeEmbed(title=title, description=description, fields=fields or [])]
    message = FakeMessage(content=content, embeds=embeds)
    text = bot.collect_message_text(message)
    data = bot.parse_join_log_message(message)
    return {
        "label": label,
        "is_join_log": bot.is_join_log(text),
        "parsed": data is not None,
        "reason": "" if data else gate_fail_reason(text),
        "data": data,
        "flattened_preview": text.replace("\n", " | ")[:120],
    }


PIKANTO_SAMPLES = [
    (
        "Plain text + Target Server:",
        """New Member Joined!
Username: het.nohate
User ID: 123456789012345678
Date: 06/02/2026
Time: 9:29 PM
Target Server: Invest With Charan""",
    ),
    (
        "Plain text + Server:",
        """New Member Joined!
Username: viper0990
User ID: 999888777666555444
Server: Profit Insider""",
    ),
    (
        "Embed flattened with colons (collect_message_text)",
        None,
        {
            "title": "New Member Joined!",
            "fields": [
                FakeField("Username", "drkvior"),
                FakeField("User ID", "111222333444555666"),
                FakeField("Target Server", "Profit League"),
                FakeField("Date", "06/03/2026"),
                FakeField("Time", "9:25 PM"),
            ],
        },
    ),
]

# Plausible Stevo / klentozz server log-bot shapes (73-server ecosystem)
STEVO_SAMPLES = [
    (
        "Pikanto-identical shape (would PASS if Stevo used same bot)",
        """New Member Joined!
Username: stevo_user
User ID: 987654321098765432
Target Server: Chill Trading""",
    ),
    (
        "Embed without colons — name/value on separate lines",
        None,
        {
            "title": "New Member Joined!",
            "fields": [
                FakeField("Username", "stevo_user"),
                FakeField("User ID", "987654321098765432"),
                FakeField("Target Server", "Chill Trading"),
            ],
            "broken_flatten": True,
        },
    ),
    (
        "Embed WITH colons via collect_message_text (current code)",
        None,
        {
            "title": "New Member Joined!",
            "fields": [
                FakeField("Username", "stevo_user"),
                FakeField("User ID", "987654321098765432"),
                FakeField("Server", "Connor's server"),
            ],
        },
    ),
    (
        "Member Join header (not New Member Joined!)",
        """Member Join
Username: stevo_user
User ID: 987654321098765432
Server: Profit Insider""",
    ),
    (
        "Discord ID: instead of User ID:",
        """New Member Joined!
Username: stevo_user
Discord ID: 987654321098765432
Server: Bullprint LLC""",
    ),
    (
        "User ID as mention only",
        """New Member Joined!
Username: stevo_user
Member: <@987654321098765432>
Server: Candle Cartel LLC""",
    ),
    (
        "User Joined phrase",
        """User Joined
Username: stevo_user
User ID: 987654321098765432
Server: Hurst Cycles""",
    ),
    (
        "Markdown bold labels in description",
        """**New Member Joined!**
**Username:** stevo_user
**User ID:** 987654321098765432
**Target Server:** ASCEND ANGELS""",
    ),
    (
        "Welcome channel MEE6-style",
        """Welcome @stevo_user to the server!
Username: stevo_user
User ID: 987654321098765432""",
    ),
    (
        "Discord timestamp only (no join phrase)",
        """Username: stevo_user
User ID: 987654321098765432
Server: Cove Trader
Joined <t:1717430400:R>""",
    ),
    (
        "Member: label instead of Username:",
        """New Member Joined!
Member: stevo_user
User ID: 987654321098765432
Server: BITBULL - Trading""",
    ),
    (
        "userid one word (no space)",
        """New Member Joined!
Username: stevo_user
Userid: 987654321098765432
Server: Abundance Avenue""",
    ),
]

# Broken flatten: old bug where fields were name\\nvalue without colons
def broken_flatten(title, fields):
    parts = ["", title]
    for f in fields:
        parts.append(f.name)
        parts.append(f.value)
    return "\n".join(parts)


def print_results(brand: str, results: list[dict]) -> None:
    passes = [r for r in results if r["parsed"]]
    fails = [r for r in results if not r["parsed"]]

    print()
    print("=" * 70)
    print(f"{brand} — local parser test results")
    print("=" * 70)

    if passes:
        print(f"\n{brand}-shaped messages that PASS ({len(passes)})")
        print("-" * 70)
        print(f"{'Sample':<45} {'is_join_log':<12} Parsed")
        for r in passes:
            print(f"{r['label']:<45} {str(r['is_join_log']):<12} PASS")

    if fails:
        print(f"\n{brand}-shaped messages that FAIL ({len(fails)})")
        print("-" * 70)
        print(f"{'Sample':<45} {'is_join_log':<12} Why")
        for r in fails:
            print(f"{r['label']:<45} {str(r['is_join_log']):<12} {r['reason']}")

    print(f"\nSummary: {len(passes)} PASS / {len(fails)} FAIL / {len(results)} total")


def main():
    pikanto_results = []
    for item in PIKANTO_SAMPLES:
        if len(item) == 2:
            label, text = item
            pikanto_results.append(run_sample(label, text))
        else:
            label, _, embed_kw = item
            pikanto_results.append(run_embed_sample(label, **embed_kw))

    stevo_results = []
    for item in STEVO_SAMPLES:
        if len(item) == 2:
            label, text = item
            stevo_results.append(run_sample(label, text))
        else:
            label, _, embed_kw = item
            if embed_kw.pop("broken_flatten", False):
                text = broken_flatten(embed_kw.get("title", ""), embed_kw.get("fields", []))
                stevo_results.append(run_sample(label, text))
            else:
                stevo_results.append(run_embed_sample(label, **embed_kw))

    print_results("PIKANTO", pikanto_results)
    print_results("STEVO", stevo_results)

    print()
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    p_pass = sum(1 for r in pikanto_results if r["parsed"])
    s_pass = sum(1 for r in stevo_results if r["parsed"])
    print(f"  Pikanto reference samples : {p_pass}/{len(pikanto_results)} pass (expect all)")
    print(f"  Stevo plausible samples     : {s_pass}/{len(stevo_results)} pass")
    if s_pass < len(stevo_results):
        print("  -> Many Stevo-like shapes fail the current parser.")
        print("  -> Paste a REAL klentozz join log below to match exact format.")
    print()
    print("To test your real message, edit REAL_STEVO_MESSAGE at bottom of this file.")


REAL_STEVO_MESSAGE = """
PASTE A REAL JOIN LOG FROM klentozz DISCORD HERE
"""


if __name__ == "__main__":
    main()
    text = REAL_STEVO_MESSAGE.strip()
    if text and "PASTE A REAL" not in text:
        print()
        print("=" * 70)
        print("REAL STEVO MESSAGE (from Discord)")
        print("=" * 70)
        r = run_sample("Your pasted message", text)
        print(f"  is_join_log    : {r['is_join_log']}")
        print(f"  parse_join_log : {'PASS' if r['parsed'] else 'FAIL'}")
        if r["parsed"]:
            for k, v in r["data"].items():
                print(f"    {k}: {v}")
        else:
            print(f"  Missing       : {r['reason']}")
