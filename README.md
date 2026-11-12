# RTP Tracker — Slot Analytics (Telegram bot)

Telegram bot with the published RTP, volatility and house edge for popular slots, grouped by provider.
English only, no CTA / affiliate links yet. Python 3.11+, aiogram 3, long polling.

## What it does

- `/start` menu: **By provider**, **Top RTP**, **By volatility**, **How to read RTP**
- Type any slot name (typos are tolerated) to open its card
- Card: RTP, house edge (100 − RTP), volatility, other known RTP builds, a data-confidence label
- On startup the bot sets its own description, short description and command menu

## Run locally

```bash
pip install -r requirements.txt
export BOT_TOKEN=...        # from @BotFather
python main.py
```

Tests: `pip install pytest && pytest -q`

## Deploy on Railway

1. New project → deploy from this repo (Nixpacks picks up `requirements.txt` and `Procfile`).
2. Add the variable `BOT_TOKEN`.
3. Make sure the service runs as a worker (no port needed).

Only one instance may poll a token at a time. Do not run it locally while it is deployed.

## Data

All slots live in `data/slots.json`. To add or fix a slot, edit that file, nothing else.

| field | meaning |
|---|---|
| `id` | short unique slug (used in button callbacks) |
| `rtp` | headline published RTP, in % |
| `vol` | `Low`, `Low-Medium`, `Medium`, `Medium-High`, `High`, `Very High` or `null` |
| `alt` | other certified RTP builds, optional |
| `conf` | `multi` (2+ sources agree), `single` (one source), `conflict` (sources disagree) |
| `range` | `[low, high]`, required when `conf` is `conflict` |
| `note`, `jackpot` | optional |

The figures were compiled from public game-info and review pages, not from the providers' own
certification documents. Before promoting the bot, verify the numbers you care about against the provider's
game page and the in-game info screen, and update `updated` in the JSON.

## Layout

```
main.py              entry point
rtpbot/data.py       catalog, search, rankings
rtpbot/texts.py      all copy
rtpbot/keyboards.py  inline keyboards and pagination
rtpbot/handlers.py   handlers
data/slots.json      slot data
tests/               data and logic tests
```
