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

**If build fails with `No such file or directory: requirements.txt`:** set **Root Directory** to `bot`, or redeploy after pulling latest `main` (repo root includes a launcher).

Create **four separate** Background Workers, all pointing at this repo.

| Service name       | CLIENT_NAME   | TOKEN / CHAT_ID        |
|--------------------|---------------|-------------------------|
| scraper-pikanto    | Pikanto       | pikanto200 credentials  |
| scraper-stevo      | Stevo         | klentozz credentials    |
| scraper-emenite1   | Emenite 1     | rp.profits_2 credentials |
| scraper-emenite2   | Emenite 2     | lost1millionn credentials |

Each service:

- **Root Directory:** `bot` (recommended) — or leave blank and use repo-root `bot.py` + `requirements.txt`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`
- **Environment:** see table below, `PYTHON_VERSION=3.11.9`

| Worker | `CLIENT_INDEX` | Token env | Group chat env |
|--------|----------------|-----------|----------------|
| Pikanto | `1` (default) | `TOKEN` or `TOKEN_CLIENT_1` | `CHAT_ID` or `CHAT_ID_CLIENT_1` |
| Stevo | `2` | `TOKEN` or `TOKEN_CLIENT_2` | `CHAT_ID` or `CHAT_ID_CLIENT_2` |
| Emenite 1 | `3` | `TOKEN` or `TOKEN_CLIENT_3` | `CHAT_ID` or `CHAT_ID_CLIENT_3` |
| Emenite 2 | `4` | `TOKEN` or `TOKEN_CLIENT_4` | `CHAT_ID` or `CHAT_ID_CLIENT_4` |

Also set `CLIENT_NAME` (e.g. `Stevo`) for log labels.

After deploy, **retire the old combined multi-account service** if it still exists (one process with 4 tokens + smart routing). Each brand worker only sees joins that **its own Discord account** can read.

### Why Pikanto “still worked” after splitting workers

The **old** setup ran **all accounts in one Render process**. Any account could see a join log; a router sent the alert to Pikanto / Stevo / Emenite based on which accounts were in that server (Clients 2–4 beat Client 1 on shared servers).

The **new** setup is **one account per worker**. The Stevo worker (`klentozz`) only forwards joins that **klentozz** actually receives in Discord. If only the Pikanto account is in a server, or only Pikanto sees the log channel, the Stevo worker will never fire — even though Pikanto’s worker still works.

**Checklist for Stevo (and each brand):**

1. Render env uses that brand’s **token** and **group chat ID** (not Pikanto’s `CHAT_ID`).
2. Open the group chat named in logs (e.g. `Stevo Auto Wise`) on the **same account** as the token — search for the startup **message id** from logs if you do not see a ping.
3. That user account is a **member of every server** whose joins you want (same as when you used multi-account routing).
4. Only **new** joins after the worker starts are forwarded (no backlog replay).
5. Optional: `DEBUG_JOIN_LOGS=true` on Render to log near-miss log messages in the dashboard.

After deploy, retire the old combined multi-account service (root multi-token `bot.py` removed).

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
