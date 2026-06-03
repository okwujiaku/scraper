# Discord Join Scraper — multi-account (one Render worker)

One Background Worker runs **all brand accounts** together. Each account watches Discord;
a **router** sends join alerts to the correct group chat (Pikanto / Stevo / Emenite).

## What you need on Render (one service)

Set **all** of these in Environment (Render does **not** use your local `.env`):

```
TOKEN_CLIENT_1=...     CHAT_ID_CLIENT_1=...   # Pikanto → Auto Wise
TOKEN_CLIENT_2=...     CHAT_ID_CLIENT_2=...   # klentozz → Stevo Auto Wise
TOKEN_CLIENT_3=...     CHAT_ID_CLIENT_3=...   # Emenite 1
TOKEN_CLIENT_4=...     CHAT_ID_CLIENT_4=...   # Emenite 2
PYTHON_VERSION=3.11.9
```

Optional per-brand server routing:

```
MONITOR_SERVERS_CLIENT_1=Invest With Charan
MONITOR_SERVERS_CLIENT_2=Chill Trading,Profit Insider,Connor
```

- **Build:** `pip install -r requirements.txt`
- **Start:** `python bot.py`
- **Root directory:** repo root (not `bot/`)

## How it works

1. Log bots post `New Member Joined!` with `Username:`, `User ID:`, `Server:` (or `Target Server:`).
2. Any connected account that **sees** that message triggers a capture.
3. The **router** picks which group gets the alert (Clients 4→3→2→1 beat Client 1 on shared servers).
4. Discord message format: **NEW MEMBER CAPTURED** card (date/time from the log bot text).

## Repo layout

```
bot.py              ← main app (multi-account) — deploy this
requirements.txt
bot/                ← optional single-account copy (not used by default start command)
```

## Local run

```bash
cp bot/.env.example .env   # or use your root .env with TOKEN_CLIENT_1..4
pip install -r requirements.txt
python bot.py
```

Self-botting violates Discord ToS; use at your own risk.
