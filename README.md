# Top Winners drip-push bot — Railway edition

Telegram bot (aiogram 3) that sends banner posts to its subscribers in private chat **on a personal schedule counted from the moment each person pressed /start**. Each post is one of 11 bundled images with three game names + RTP captions and one button that opens a Telegram Mini App. Long polling; no HTTP server or public port needed.

## How it works

- A user presses **/start** → becomes a subscriber, gets `WELCOME_TEXT`, and their personal timer starts. **/stop** unsubscribes.
- The first push arrives after the first value of `DRIP_DELAYS`; each next push arrives after the next value, counted from the previous push. Every user has their own timer.
- Posts go in order 1 → 11 for every user. When the list of delays ends, that user gets no more automatic pushes.
- Users who block the bot are removed automatically. If the bot was offline, overdue pushes are sent once, with no catch-up bursts.
- The button under each post opens the Mini App from `MINIAPP_URL`.

### DRIP_DELAYS

Comma-separated pauses, units `m` (minutes), `h` (hours), `d` (days). **One value = one push.**

Default: `15m,2h,5h,12h,20h,1d,2d,3d,4d,5d,7d` — 11 pushes: four in the first ~20 hours, then roughly daily, then fading to every few days. Make the first values short and later ones long to keep "more at the start, then tapering off". Add values to send more than 11 pushes (posts cycle).

## Deploy on Railway

1. Upload this **folder's content** to a private GitHub repository (not a ZIP as the repo root), or deploy with the Railway CLI.
2. Railway → **New Project → Deploy from GitHub repo**.
3. Service → **Variables**:
   - `BOT_TOKEN` — token from BotFather.
   - `ADMIN_IDS` — your numeric Telegram user ID (several IDs comma-separated).
   - `MINIAPP_URL` — direct Mini App link `https://t.me/<bot_username>/<app_short_name>` (optionally `?startapp=param`). Create the app in BotFather with `/newapp`. (Old name `PLAY_URL` still works.)
   - `DATA_FILE` — `/data/data.json` (see the Volume below).
   - Optional: `DRIP_DELAYS`, `BUTTON_TEXT`, `WELCOME_TEXT`, `STOP_TEXT`.
4. **Add a Volume** mounted at `/data`. **Required:** subscribers and their timers live in that file; without a Volume every redeploy/restart wipes them all.
5. Set **one replica only** (long polling does not work with several instances on one token).
6. Open the bot, send `/start`, then `/dripnow` to see the chain work on yourself.

No domain or healthcheck needed; this is a background worker.

## Commands

For everyone: `/start`, `/stop`.

For admins (private chat):

- `/posts` — list all 11 presets.
- `/preview 9` / `/preview custom` — show a post **only to you** (`/preview` alone shows post 1).
- `/publish 9` / `/publish custom` — one-off push of that post to **all subscribers** right now (a number is required, to avoid accidental blasts). Does not affect personal chains.
- `/setgames` + three lines `Game Name | 99.20` — edit the custom post.
- Photo with caption `/setimage` (or `/setimage https://...`) — set the custom banner.
- `/dripon`, `/dripoff` — resume / pause the chain for everyone (on by default).
- `/dripnow` — test the chain on yourself: your next push is sent immediately.
- `/status` — subscribers, how many are still in the chain, time to the nearest push, the pauses.

## Notes

- Users only receive pushes if they pressed /start themselves (Telegram does not allow messaging people first).
- Pushes go out at about 20 messages/second.
- The coloured squares are decorative, **not** a measured win probability. RTP values are editable editorial examples, not live casino data; do not present them as such.
- Local run: `python -m pip install -r requirements.txt && python bot.py` (Python 3.11+, `.env` next to `bot.py`). Never commit secrets.

## The 11 image posts

Posts 1 and 11 use identical images (the two source files were byte-identical) and stay independently addressable. `/posts` shows the full mapping.
