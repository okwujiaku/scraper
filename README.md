# Discord Join Scraper (Option C — one worker per customer)

One simple bot, many deployments. Each customer (or brand) gets their own **Render Background Worker** with only `TOKEN` + `CHAT_ID`.

## Repo layout

```
bot/                 ← shared code (deploy this folder on Render)
  bot.py
  requirements.txt
  .env.example
scripts/
  new-customer.sh    ← checklist for adding a paying customer
templates/
  render-env.example
```

## Local run

```bash
cd bot
cp .env.example .env
# Edit .env with TOKEN, CHAT_ID, CLIENT_NAME
pip install -r requirements.txt
python bot.py
```

## Render — your 4 brands (create 4 Background Workers)

Create **four separate** Background Workers, all pointing at this repo with **Root Directory = `bot`**.

| Service name       | CLIENT_NAME   | TOKEN / CHAT_ID        |
|--------------------|---------------|-------------------------|
| scraper-pikanto    | Pikanto       | pikanto200 credentials  |
| scraper-stevo      | Stevo         | klentozz credentials    |
| scraper-emenite1   | Emenite 1     | rp.profits_2 credentials |
| scraper-emenite2   | Emenite 2     | lost1millionn credentials |

Each service:

- **Root Directory:** `bot`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`
- **Environment:** `TOKEN`, `CHAT_ID`, `CLIENT_NAME`, `PYTHON_VERSION=3.11.9`

After deploy, retire the old combined multi-account service (root `bot.py` removed).

## Add paying customer #5+

```bash
./scripts/new-customer.sh customer-john "John Smith"
```

Then create another Background Worker with the same `bot/` root and that customer's `TOKEN` + `CHAT_ID`.

## How it works

1. This Discord **user account** must be in servers where the join log bot posts.
2. The worker detects "New Member Joined!" log messages.
3. It forwards a formatted card to the configured **group chat**.

No routing, no server lists — same model that works for Pikanto.

## Notes

- Self-botting violates Discord ToS; use at your own risk.
- Free Render tier allows ~1 background worker; multiple brands need paid workers (~$7/mo each).
