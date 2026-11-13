# Top Winners drip-push bot — Railway edition

Telegram bot (aiogram 3) that sends banner posts to subscribers in private chat **on a personal schedule counted from each person's /start**, and tracks where they came from (Telegram Ads tag), who clicked, who registered and who deposited. Each post is one of 11 bundled images with three game names + RTP captions and one button that opens the Mini App.

## How it works

- **/start** → the user becomes a subscriber, gets `WELCOME_TEXT`, and their personal timer starts. **/stop** unsubscribes.
- Pushes follow `DRIP_DELAYS` (see below), posts in order 1 → 11 per user. After the list ends, no more automatic pushes.
- Users who block the bot are marked as left automatically. If the bot was offline, overdue pushes go out once (no catch-up bursts).
- When an **FTD postback** arrives for a user, their chain stops (`STOP_ON_FTD=0` to disable).

### DRIP_DELAYS

Comma-separated pauses (`m` minutes, `h` hours, `d` days). **One value = one push.** The first is the pause after /start, each next one the pause after the previous push. Default: `15m,2h,5h,12h,20h,1d,2d,3d,4d,5d,7d` (four pushes in the first ~20 hours, then fading out).

## Attribution and results (same scheme as the cp-machine / Meta Arena bot)

**Start tag.** Telegram Ads link: `https://t.me/<bot>?start=<tag>` — the tag is the source in `/stats` (no tag = `organic`). Only the first tag counts as the user's source; repeat starts are counted separately.

**PropellerAds click id.** Put the SUBID after a double underscore: `https://t.me/<bot>?start=<tag>__{SUBID}` (either order works; a part starting with `users_` is treated as the tag). The SUBID is stored on the user and used for S2S postbacks.

**Clicks.** With a public domain the button opens `<domain>/r?sub2=<telegram_id>&sub3=p<N>`, which counts the click (once per user and push) and redirects to `MINIAPP_URL` with the user's Telegram id appended (`startapp=<id>` for t.me links, `click_id=<id>` for normal links; `CLICK_PARAM` overrides). If the final link is an affiliate/tracker URL, include its own postback parameter, otherwise the id is lost.

**Results.** In the partner panel set the postback URL to `https://<domain>/postback/coinplay`:
- registration: `?subid={click_id}&reg={reg}`
- first deposit: `?subid={click_id}&ftd={ftd}`

(`click_id=` instead of `subid=` and `status=reg|ftd` are also accepted; `&payout=`/`&amount=` is passed on to Propeller. Add `&key=<POSTBACK_SECRET>` if you set a secret.) Check the chain with `/pbtest` and `/pbcheck`.

**PropellerAds S2S.** Set `PROPELLER_URL` (reg is sent as is, FTD gets `&goal=2` appended) or separate `PROPELLER_URL_REG` / `PROPELLER_URL_FTD`. Placeholders: `{external_id}` or `{visitor_id}` = SUBID, `{payout}` or `{conversion_revenue}` = amount. Each user's reg/FTD is sent at most once. `/proppb` shows the status, `/proppb retry` resends what was not delivered.

## Deploy on Railway

1. Upload this **folder's content** to a private GitHub repository (not a ZIP as the repo root), then Railway → **New Project → Deploy from GitHub repo**.
2. **Variables:** `BOT_TOKEN`, `ADMIN_IDS` (numeric Telegram IDs, comma-separated), `MINIAPP_URL`, `DATA_FILE=/data/data.json`; optional ones are in `.env.example`.
3. **Volume** mounted at `/data`. Required: subscribers, timers and all stats live there; without it a redeploy wipes everything.
4. **Settings → Networking → Generate Domain.** Required for click counting and postbacks (`PORT` and `RAILWAY_PUBLIC_DOMAIN` are provided by Railway). Without a domain the bot still sends pushes but cannot count clicks or receive results.
5. **One replica only** (long polling does not work with several instances on one token).
6. Send `/start`, then `/dripnow`, `/pbtest`.

## Commands

For everyone: `/start`, `/stop`.

Admins (private chat):

- `/posts`, `/preview 9` (only to you), `/publish 9` (one-off push to all active subscribers, number required), `/preview custom`, `/publish custom`, `/setgames`, `/setimage`.
- `/dripon`, `/dripoff` — resume / pause the chain for everyone. `/dripnow` — test the chain on yourself.
- `/stats` — starts, unique, active/left, pushes sent, clicks, reg, FTD, per-push CTR and per-source table (`/stats full` for everything).
- `/status` — subscribers, timers, tracking mode, S2S state.
- `/pbcheck`, `/pbtest` — postback counters, last hits, the URL for the partner panel; test hit.
- `/proppb`, `/proppb retry` — PropellerAds S2S.
- `/markreg <id> [<id>…]`, `/markftd <id> [payout]` — mark manually if the partner postback does not fire (also triggers Propeller S2S and stops the chain on FTD).

Files in the Volume: `data.json` (users and stats), `events.jsonl` (start / click / reg / ftd log), `postbacks.jsonl` (every postback hit).

## Notes

- Users receive pushes only after pressing /start themselves.
- Pushes go out at about 20 messages/second.
- Stats are computed from user records; source = the user's first start tag.
- The coloured squares are decorative, **not** a measured win probability. RTP values are editable editorial examples, not live casino data.
- Local run: `python -m pip install -r requirements.txt && python bot.py` (Python 3.11+, `.env` next to `bot.py`). Never commit secrets.

## The 11 image posts

Posts 1 and 11 use identical images (the two source files were byte-identical). `/posts` shows the full mapping.
