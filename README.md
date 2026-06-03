# Discord Join Scraper (Option C — one worker per brand)

One simple bot, **four Render Background Workers** (Pikanto, Stevo, Emenite 1, Emenite 2). Each worker runs **one Discord account** and forwards to **one group chat**.

## What went wrong before (lessons from the working logs)

The old **multi-account** setup worked because one process + a router sent joins to the right group. When we split to Option C, these were the real bugs — not “Option C is bad”:

1. **`CHAT_ID` missing on Render** — bot captured joins in logs but never sent to Discord (`No target chat ID configured`).
2. **`pending_payments: null` crash** — fixed with a startup library patch (kept in `bot/bot.py`).
3. **Parser / message drift** — extra layers (poll loops, `_live_after`, new card layout) replaced the simple `on_message` + **NEW MEMBER CAPTURED** flow that worked.
4. **Embed log bots** — fields must flatten as `Username: value` or `username:` never appears in text.

Option C is restored to the **simple working model** per worker, with only those fixes kept.

## Render — one worker per brand

| Service | Account | Env on **that** worker |
|---------|---------|-------------------------|
| scraper-pikanto | pikanto200 | `DISCORD_TOKEN` or `TOKEN_CLIENT_1`, `CHAT_ID` or `CHAT_ID_CLIENT_1` |
| scraper-stevo | klentozz | `DISCORD_TOKEN`, `CHAT_ID_CLIENT_1` = Stevo group id (or `CLIENT_INDEX=2` + `_CLIENT_2`) |
| scraper-emenite1 | rp.profits_2 | token + chat for Emenite 1 |
| scraper-emenite2 | lost1millionn | token + chat for Emenite 2 |

Each service:

- **Root Directory:** `bot` (recommended) or repo root (`bot.py` launcher)
- **Build:** `pip install -r requirements.txt`
- **Start:** `python bot.py`
- **Env:** token + chat id + `CLIENT_NAME` + `PYTHON_VERSION=3.11.9`

**Important:** Render never reads your local `.env`. Every variable must be in the Render dashboard for **each** worker.

## How each worker behaves

1. Logs in as **one** user account.
2. Listens with **`on_message`** for log-bot posts containing `Username:`, `User ID:`, and `New Member Joined!`.
3. Parses Date, Time, Username, User ID, Server (or Target Server) from the message.
4. Sends the **NEW MEMBER CAPTURED** markdown card to **that worker’s** group chat only.
5. That account must be **in the servers** where join logs appear — no cross-brand router.

## Local run

```bash
cd bot
cp .env.example .env
pip install -r requirements.txt
python bot.py
```

Self-botting violates Discord ToS; use at your own risk.
