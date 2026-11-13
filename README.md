# Top Winners push bot — Railway edition

Telegram bot (aiogram 3) that **pushes banner posts to its subscribers in private chat**. Each post is one of 11 bundled images with three game names + RTP captions and one button that opens a Telegram Mini App. Long polling; no HTTP server or public port needed.

## How it works

- A user presses **/start** → becomes a subscriber and receives `WELCOME_TEXT`. **/stop** unsubscribes.
- Users who block the bot are removed automatically.
- Admins (`ADMIN_IDS`) push posts to **all subscribers** with `/publish`, or turn on the schedule with `/autoon` (times from `POST_TIMES`, cycling through the 11 presets).
- The button under each post opens the Mini App from `MINIAPP_URL`.

## Deploy on Railway

1. Upload this **folder's content** to a private GitHub repository (not a ZIP as the repo root), or deploy with the Railway CLI.
2. Railway → **New Project → Deploy from GitHub repo**.
3. Service → **Variables**:
   - `BOT_TOKEN` — token from BotFather.
   - `ADMIN_IDS` — your numeric Telegram user ID (several IDs comma-separated).
   - `MINIAPP_URL` — direct Mini App link `https://t.me/<bot_username>/<app_short_name>` (optionally `?startapp=param`). Create the app in BotFather with `/newapp`. (Old name `PLAY_URL` still works.)
   - Optional: `BUTTON_TEXT`, `WELCOME_TEXT`, `STOP_TEXT`, `TIMEZONE`, `POST_TIMES`, `DATA_FILE`.
4. **Add a Volume** mounted at `/app/data` and set `DATA_FILE=/app/data/data.json`. **This is required here:** the subscriber list lives in that file, and without a Volume every redeploy/restart wipes all subscribers (users would have to press /start again).
5. Set **one replica only** (long polling does not work with several instances on one token).
6. Open the bot, send `/start`, then `/preview 9` and `/publish 9`.

No domain or healthcheck needed; this is a background worker.

## Commands

For everyone: `/start`, `/stop`.

For admins (private chat):

- `/posts` — list all 11 presets.
- `/preview` / `/preview 9` / `/preview custom` — show a post **only to you**.
- `/publish` / `/publish 9` / `/publish custom` — **push to all subscribers** and advance the rotation. Reports delivered / blocked / errors.
- `/setgames` + three lines `Game Name | 99.20` — edit the custom post.
- Photo with caption `/setimage` (or `/setimage https://...`) — set the custom banner.
- `/autoon`, `/autooff` — scheduled pushes at `POST_TIMES` in `TIMEZONE` (off by default).
- `/status` — subscribers count, button link, schedule, next banner.

## Notes

- Users only receive pushes if they pressed /start themselves (Telegram does not allow messaging people first).
- Sending runs at about 20 messages/second, so a base of 10,000 subscribers takes roughly 8–9 minutes per push.
- The coloured squares are decorative, **not** a measured win probability. RTP values are editable editorial examples, not live casino data; do not present them as such.
- Local run: `python -m pip install -r requirements.txt && python bot.py` (Python 3.11+, `.env` next to `bot.py`). Never commit secrets.

## The 11 image posts

Posts 1 and 11 use identical images (the two source files were byte-identical) and stay independently addressable. `/posts` shows the full mapping.
