# Telegram Top Winners bot — Railway edition

Telegram post publisher powered by aiogram 3, with **11 bundled image presets**, three game names, RTP captions and one URL button that opens a Telegram Mini App. Uses long polling; no HTTP server or public port is needed.

## Deploy on Railway

1. Upload this **folder's content** to a private GitHub repository (do not upload a ZIP as the repository root). You can also deploy with the Railway CLI.
2. Railway → **New Project → Deploy from GitHub repo** → select the repository.
3. Railway → service → **Variables** → create:
   - `BOT_TOKEN` — token issued by BotFather.
   - `ADMIN_IDS` — your Telegram numeric user ID (multiple IDs comma-separated).
   - `CHANNEL_ID` — `@channelname` for public channels, or `-100...` for private channels.
   - `MINIAPP_URL` — direct link to the Mini App, format `https://t.me/<bot_username>/<app_short_name>` (optionally `?startapp=param`). The button under every post opens this Mini App. The app must be created in BotFather via `/newapp`. (Old name `PLAY_URL` still works as a fallback.)
   - Optional: `BUTTON_TEXT`, `TIMEZONE`, `POST_TIMES`, `DATA_FILE`.
4. Add the Telegram bot as **administrator** of your channel with permission to post messages.
5. Railway deploys using `railway.json` → `python bot.py`. Set **one replica only**, since concurrent long polling is not supported for one token.
6. Open the bot's private chat and send `/start`, then `/preview 9` and `/publish 9`.

You do **not** need to expose a domain or configure a healthcheck; this is a background worker.

## Commands (private chat with authorized admin)

- `/posts` — list all 11 presets.
- `/preview` — preview next banner in rotation; `/preview 9` — specific banner.
- `/publish` — publish next banner and advance rotation; `/publish 9` — publish specific banner and advance rotation.
- `/setgames` followed by three lines like `Game Name | 99.20` — edit custom post.
- Send a photo with caption `/setimage` — set custom banner; alternatively `/setimage https://...`.
- `/preview custom` and `/publish custom` — use custom game names and banner.
- `/autoon`, `/autooff` — toggle scheduled posts, in time zone configured with `TIMEZONE`.
- `/status` — current settings.

A scheduled run cycles the 11 presets. Scheduling starts **off** by default; enable explicitly in private chat.

## Persistence on Railway

Railway's ordinary container filesystem is ephemeral. Changes made using `/setgames`, `/setimage`, `/autoon`, and the rotation index may reset after a restart/redeploy unless a **Railway Volume** is mounted. For persistent settings, add a volume mounted at `/app/data` (check your service working directory) and set `DATA_FILE=/app/data/data.json`. The bundled image assets are part of the repository and survive rebuilds. Custom Telegram photo `file_id` can be reused by the same bot token.

## Notes

The screenshot-inspired colored squares are decorative; **they are not a measured win probability or a predictive signal**. All RTP values are editable editorial examples and not verified real-time slot RTP values. Do not claim they're live casino data. If you intend to show real RTP, connect a verifiable provider feed and label its source/time period.

Use `python -m pip install -r requirements.txt && python bot.py` for local use (Python 3.11+). Place `.env` next to `bot.py` locally. Never commit secrets.

## All 11 uploaded image posts

Every uploaded image is kept separately. Posts 1 and 11 use identical image content because the two source files supplied for them were byte-for-byte identical; both remain independently addressable with `/preview 1` and `/preview 11`. Each post has three corresponding game rows (33 game appearances across the 11 posts), though several game titles recur. `/posts` shows the full mapping.
