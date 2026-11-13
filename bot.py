"""Telegram drip-push bot with ad attribution.

* Every subscriber gets banner posts (with a Mini App button) on a personal schedule counted from /start.
* Start tags from Telegram Ads (?start=<tag>__<SUBID>) are stored per user, clicks go through /r,
  reg / FTD postbacks come back to /postback/coinplay, and are optionally forwarded to PropellerAds (S2S).
  Same scheme as the cp-machine (Meta Arena) bot.
Python 3.11+, aiogram 3, aiohttp."""
import asyncio
import copy
import html
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import ChatMemberUpdated, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets'


def env(name, default=None, required=False):
    """Read an env var; strip spaces and stray quotes (common when pasting into Railway)."""
    value = os.getenv(name)
    value = value.strip().strip('"').strip("'").strip() if value is not None else ''
    if not value:
        if required:
            raise RuntimeError(f'Переменная окружения {name} не задана (Railway → Variables)')
        return default
    return value


def parse_delays(raw):
    """'15m,12h,1d' -> [900, 43200, 86400] seconds. Fails loudly on a bad value."""
    units = {'m': 60, 'h': 3600, 'd': 86400}
    out = []
    for part in raw.split(','):
        part = part.strip().lower()
        if not part:
            continue
        m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([mhd])', part)
        if not m or float(m[1]) <= 0:
            raise RuntimeError(f'DRIP_DELAYS: неверное значение "{part}", примеры: 15m, 12h, 2d')
        out.append(int(float(m[1]) * units[m[2]]))
    if not out:
        raise RuntimeError('DRIP_DELAYS пуст')
    return out


def human(seconds):
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f'{max(1, round(seconds / 60))} мин'
    if seconds < 86400:
        return f'{seconds / 3600:.1f} ч'.replace('.0 ', ' ')
    return f'{seconds / 86400:.1f} дн'.replace('.0 ', ' ')


BOT_TOKEN = env('BOT_TOKEN', required=True)
try:
    ADMIN_IDS = {int(v) for v in env('ADMIN_IDS', required=True).split(',') if v.strip()}
except ValueError:
    raise RuntimeError('ADMIN_IDS: нужны числовые Telegram ID через запятую') from None
# Mini App link used by the post button. MINIAPP_URL is the new name; PLAY_URL still works as a fallback.
MINIAPP_URL = env('MINIAPP_URL') or env('PLAY_URL')
if not MINIAPP_URL:
    raise RuntimeError('Переменная окружения MINIAPP_URL не задана (Railway → Variables)')
IS_TME = bool(re.match(r'https://(t|telegram)\.me/', MINIAPP_URL))
BUTTON_TEXT = env('BUTTON_TEXT', '🎰 PLAY NOW!')
WELCOME_TEXT = env('WELCOME_TEXT', '✅ You are subscribed! The top slots by RTP will arrive right here. Send /stop to unsubscribe.')
STOP_TEXT = env('STOP_TEXT', '⏸ Unsubscribed. Send /start to subscribe again.')
# Pause before the 1st push (counted from /start), then the pause after each push before the next one.
# One entry = one push. Posts go in the order 1..11 and cycle if there are more than 11 entries.
DRIP_DELAYS = parse_delays(env('DRIP_DELAYS', '15m,2h,5h,12h,20h,1d,2d,3d,4d,5d,7d'))
DATA_FILE = Path(env('DATA_FILE', str(ROOT / 'data.json')))
EVENTS_FILE = DATA_FILE.with_name('events.jsonl')
POSTBACKS_FILE = DATA_FILE.with_name('postbacks.jsonl')

# --- tracking / postbacks (same scheme as the cp-machine bot) ---
PORT = int(env('PORT', '8080'))
PUBLIC_URL = (env('PUBLIC_URL') or (f"https://{env('RAILWAY_PUBLIC_DOMAIN')}" if env('RAILWAY_PUBLIC_DOMAIN') else '')).rstrip('/')
# Button goes through <PUBLIC_URL>/r (counts the click, appends the user id) when a public domain exists.
TRACK_CLICKS = bool(PUBLIC_URL) and env('TRACK_CLICKS', '1') != '0'
# Query param that carries the user's Telegram id to the target (partner/tracker macro click_id; Mini App start param).
CLICK_PARAM = env('CLICK_PARAM', 'startapp' if IS_TME else 'click_id')
POSTBACK_SECRET = env('POSTBACK_SECRET', '')  # optional: if set, postbacks must carry &key=<secret>
STOP_ON_FTD = env('STOP_ON_FTD', '1') != '0'  # stop the push chain once an FTD postback arrives
PROP_URL = env('PROPELLER_URL', '')
PROP_URL_REG = env('PROPELLER_URL_REG') or PROP_URL
PROP_URL_FTD = env('PROPELLER_URL_FTD') or (
    (PROP_URL + ('' if re.search(r'[?&]goal=', PROP_URL) else ('&' if '?' in PROP_URL else '?') + 'goal=2')) if PROP_URL else '')
PROP_PAYOUT = {'reg': env('PROPELLER_PAYOUT_REG', '0'), 'ftd': env('PROPELLER_PAYOUT_FTD', '0')}

RETRY_SECONDS = 600   # retry a failed send after 10 minutes
MAX_FAILS = 5         # after this many failures in a row for one user, skip that post
BROADCAST_DELAY = 0.05  # ~20 msgs/sec, safely below Telegram's ~30/sec limit
TICK_SECONDS = 20

# Artwork is supplied by the project owner. Each preset's game names match its banner.
# RTP values are editorial placeholders, not a casino feed or a prediction of wins.
PRESETS = [
    {'image': '01_sugar_jokers_pinata.jpg', 'games': [('Sugar Rush 1000', 99.89), ("Joker’s Jewels Hot", 98.13), ('Pinata Wins', 97.45)]},
    {'image': '02_starzbet_princess_777_ra.jpg', 'games': [('Starzbet Princess', 99.05), ('777 Rush', 98.80), ('Coins of Ra - Hold & Win', 97.05)]},
    {'image': '03_princess_dragon_bonanza.jpg', 'games': [('Starzbet Princess', 99.68), ('Year of the Dragon King', 98.06), ('Sweet Bonanza Super Scatter', 97.15)]},
    {'image': '04_money_fire_garuda.jpg', 'games': [('Money Coming 30000', 99.11), ('Fire Strike 2', 98.35), ('Fortune Garuda 1000', 97.20)]},
    {'image': '05_olympus_olympus_sugar.jpg', 'games': [('Gates of Olympus 1000', 99.78), ('Gates of Olympus 1000', 98.47), ('Sugar Rush', 97.98)]},
    {'image': '06_money_olympus_garuda.jpg', 'games': [('Money Coming 30000', 99.21), ('Gates of Olympus 1000', 98.47), ('Fortune Garuda 1000', 97.98)]},
    {'image': '07_olympus_diamonds_bones.jpg', 'games': [('Gates of Olympus 1000', 99.30), ('3 Superpower Diamonds', 98.67), ('Caribbean Bones', 96.89)]},
    {'image': '08_zeus_garuda_empire.jpg', 'games': [('Zeus', 99.51), ('Fortune Garuda 1000', 98.39), ('Golden Empire 1000', 97.55)]},
    {'image': '09_empire_sugar_mental.jpg', 'games': [('Golden Empire 1000', 99.20), ('Sugar Rush', 98.99), ('Mental 2', 97.05)]},
    {'image': '10_garuda_triple.jpg', 'games': [('Fortune Garuda 1000', 99.00), ('Fortune Garuda 1000', 98.39), ('Fortune Garuda 1000', 97.55)]},
    # The user supplied this identical-looking file separately, so it remains its own post.
    {'image': '11_sugar_jokers_pinata_repeat.jpg', 'games': [('Sugar Rush 1000', 99.89), ("Joker’s Jewels Hot", 98.13), ('Pinata Wins', 97.45)]},
]

DEFAULT = {
    # user_id (as str) -> user record, see USER_DEFAULTS
    'subscribers': {},
    'drip_enabled': True,
    'pushes_sent': 0,
    'by_push': {},  # 'p3' / 'custom' -> pushes sent
    'custom_image': '',
    'custom_games': [
        {'name': 'Golden Empire 1000', 'rtp': 99.20},
        {'name': 'Sugar Rush', 'rtp': 98.99},
        {'name': 'Mental 2', 'rtp': 97.05},
    ],
}

USER_DEFAULTS = {
    'active': True, 'joined': 0, 'step': 0, 'next_at': None, 'fails': 0,
    'username': None, 'starts': 0, 'first_source': 'organic', 'last_source': 'organic',
    'propeller_subid': '', 'clicked_at': None, 'clicked_p': [],
    'reg_at': None, 'ftd_at': None, 'propeller_reg_at': None, 'propeller_ftd_at': None,
}


def now_ts():
    return int(time.time())


def new_sub(source='organic'):
    sub = copy.deepcopy(USER_DEFAULTS)
    sub.update(joined=now_ts(), next_at=now_ts() + DRIP_DELAYS[0], first_source=source, last_source=source)
    return sub


def load_data():
    # deepcopy: DEFAULT holds lists/dicts, a shallow copy would let runtime changes leak into it.
    data = copy.deepcopy(DEFAULT)
    if DATA_FILE.exists():
        try:
            loaded = json.loads(DATA_FILE.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                data.update(loaded)
            else:
                logging.error('Data file has unexpected format, using defaults')
        except (json.JSONDecodeError, OSError):
            logging.exception('Unable to read data file')
    if isinstance(data['subscribers'], list):  # older format: plain list of ids
        data['subscribers'] = {str(uid): new_sub() for uid in data['subscribers']}
    for sub in data['subscribers'].values():  # fields added in newer versions
        for k, v in USER_DEFAULTS.items():
            sub.setdefault(k, copy.deepcopy(v))
    return data


state = load_data()
_dirty = False


def save():
    global _dirty
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DATA_FILE)
    _dirty = False


def mark_dirty():
    """For frequent events (clicks): saved by the scheduler within TICK_SECONDS instead of on every hit."""
    global _dirty
    _dirty = True


def append_jsonl(path, record):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except OSError:
        logging.exception('Cannot write %s', path.name)


def read_jsonl_tail(path, limit):
    try:
        lines = path.read_text(encoding='utf-8').splitlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def log_event(user_id, event, **extra):
    append_jsonl(EVENTS_FILE, {'ts': now_ts(), 'user': user_id, 'event': event, **extra})


def is_admin(message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_IDS and message.chat.type == 'private')


# ---------------------------------------------------------------- users / sources
def normalize_source(raw):
    clean = re.sub(r'[^A-Za-z0-9_-]', '', str(raw or '').strip()[:64])
    return clean or 'organic'


def parse_start(payload):
    """'/start ads1' -> ('ads1', ''); '/start ads1__SUBID' -> ('ads1', 'SUBID').
    Either order works: <tag>__<SUBID> or <SUBID>__<tag> (a part starting with users_ is the tag)."""
    raw = (payload or '').strip()
    subid = ''
    m = re.fullmatch(r'([A-Za-z0-9_-]+?)__([A-Za-z0-9_-]+)', raw)
    if m:
        a, b = m.group(1), m.group(2)
        if b.lower().startswith('users_') and not a.lower().startswith('users_'):
            raw, subid = b, a
        else:
            raw, subid = a, b
    return normalize_source(raw), subid


def ensure_subscriber(user_id, source='organic'):
    """Create the user, or re-activate one who left (the chain restarts, unless they already made an FTD)."""
    key = str(user_id)
    sub = state['subscribers'].get(key)
    if sub is None:
        sub = state['subscribers'][key] = new_sub(source)
        return sub, True
    if not sub.get('active', True):
        sub['active'] = True
        sub['step'] = 0
        sub['fails'] = 0
        sub['next_at'] = None if (sub.get('ftd_at') and STOP_ON_FTD) else now_ts() + DRIP_DELAYS[0]
    return sub, False


def register_start(user_id, username, payload):
    source, subid = parse_start(payload)
    sub, is_new = ensure_subscriber(user_id, source)
    sub['last_source'] = source  # first_source is set once and never overwritten
    sub['starts'] += 1
    if username:
        sub['username'] = username
    if subid:
        sub['propeller_subid'] = subid  # latest click wins
    save()
    log_event(user_id, 'start', source=source, detail='new_user' if is_new else f'repeat_start_{sub["starts"]}')
    return sub, is_new


def subscribe(user_id):
    ensure_subscriber(user_id)
    save()


def unsubscribe(user_id, persist=True):
    sub = state['subscribers'].get(str(user_id))
    if sub and sub.get('active', True):
        sub['active'] = False
        sub['next_at'] = None
        if persist:
            save()


def active_items():
    return [(k, v) for k, v in state['subscribers'].items() if v.get('active', True)]


# ---------------------------------------------------------------- posts
def progress(rtp):
    # Decorative scale, NOT a mathematical transformation of RTP.
    if rtp >= 99:
        return '🟩' * 9 + '⬜️'
    if rtp >= 98:
        return '🟩' * 7 + '🟨' + '⬜️' * 2
    if rtp >= 97:
        return '🟩' * 6 + '🟨' + '⬜️' * 3
    return '🟩' * 5 + '🟥' + '⬜️' * 4


def format_caption(games):
    icons = ('🥇', '🥈', '🥉')
    sections = []
    for n, game in enumerate(games[:3]):
        name, rtp = game if isinstance(game, tuple) else (game['name'], game['rtp'])
        sections.append(f'{icons[n]} <b>{html.escape(str(name))}</b>\n'
                        f'🎯 <b>RTP: {float(rtp):.2f}%</b>\n'
                        f'🚀 {progress(float(rtp))}')
    return '\n\n'.join(sections)


def target_url(user_id):
    """The Mini App / offer link with the user's Telegram id appended."""
    sep = '&' if '?' in MINIAPP_URL else '?'
    return f'{MINIAPP_URL}{sep}{CLICK_PARAM}={user_id}'


def post_label(selection):
    return f'p{selection[0] + 1}' if isinstance(selection[0], int) else 'custom'


def keyboard(user_id, label):
    # With a public domain the button goes through /r: the click is counted, then redirected to the Mini App link.
    url = f'{PUBLIC_URL}/r?sub2={user_id}&sub3={label}' if TRACK_CLICKS else target_url(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BUTTON_TEXT, url=url)]])


def preset_selection(idx):
    preset = PRESETS[idx]
    return (idx, preset['games'], str(ASSETS / preset['image']))


def resolve_selection(text, allow_empty=True):
    """Accept a 1-based preset index or 'custom'. Empty means post 1 (only for previews)."""
    arg = text.strip().lower()
    if arg == 'custom':
        return ('custom', state['custom_games'], state['custom_image'])
    if not arg:
        if not allow_empty:
            raise ValueError('Укажи номер поста или custom, например: /publish 9')
        return preset_selection(0)
    if not arg.isdigit():
        raise ValueError(f'Укажи номер от 1 до {len(PRESETS)} или custom')
    idx = int(arg) - 1
    if not 0 <= idx < len(PRESETS):
        raise ValueError(f'Номер должен быть от 1 до {len(PRESETS)}')
    return preset_selection(idx)


def local_file(img):
    try:
        return Path(img).is_file()
    except (OSError, ValueError):  # file_id / long URL can't be a path
        return False


photo_cache = {}  # banner -> Telegram file_id, so each banner is uploaded once, not once per subscriber
send_lock = asyncio.Lock()  # one sending run at a time, keeps us under Telegram's rate limit


async def send_post(bot, chat_id, selection):
    _, games, img = selection
    caption = format_caption(games)
    markup = keyboard(chat_id, post_label(selection))
    if img:
        cached = photo_cache.get(img)
        photo = cached or (FSInputFile(img) if local_file(img) else img)
        msg = await bot.send_photo(chat_id, photo, caption=caption, parse_mode='HTML', reply_markup=markup)
        if not cached and msg.photo:
            photo_cache[img] = msg.photo[-1].file_id
        return msg
    return await bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=markup)


async def safe_send(bot, user_id, selection):
    """Returns 'ok', 'gone' (blocked the bot / chat missing) or 'error'."""
    try:
        try:
            await send_post(bot, user_id, selection)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            await send_post(bot, user_id, selection)
        return 'ok'
    except TelegramForbiddenError:
        return 'gone'
    except TelegramBadRequest as exc:
        if 'chat not found' in str(exc).lower():
            return 'gone'
        logging.error('Send to %s failed: %s', user_id, exc)
        return 'error'
    except Exception:
        logging.exception('Send to %s failed', user_id)
        return 'error'


def count_push(label):
    state['pushes_sent'] += 1
    state['by_push'][label] = state['by_push'].get(label, 0) + 1


async def broadcast(bot, selection):
    """Manual push of one post to every active subscriber. Returns (sent, gone, failed)."""
    async with send_lock:
        sent = gone = failed = streak = 0
        for key, _ in active_items():
            result = await safe_send(bot, int(key), selection)
            if result == 'ok':
                sent += 1
                streak = 0
                count_push(post_label(selection))
            elif result == 'gone':
                unsubscribe(key, persist=False)
                gone += 1
            else:
                failed += 1
                streak += 1
            if streak >= 5:  # same error for everyone (bad banner / URL) -> stop instead of spamming logs
                logging.error('Broadcast aborted after %s consecutive errors', streak)
                break
            await asyncio.sleep(BROADCAST_DELAY)
        save()
        return sent, gone, failed


async def drip_tick(bot):
    """Send the next post to every subscriber whose personal timer has expired."""
    if not state['drip_enabled']:
        return
    now = now_ts()
    due = [k for k, v in active_items() if v.get('next_at') and v['next_at'] <= now]
    if not due:
        return
    async with send_lock:
        for key in due:
            sub = state['subscribers'].get(key)
            if not sub or not sub.get('active', True) or not sub.get('next_at'):
                continue
            step = sub['step']
            selection = preset_selection(step % len(PRESETS))
            result = await safe_send(bot, int(key), selection)
            if result == 'gone':
                unsubscribe(key, persist=False)
            elif result == 'ok' or sub.get('fails', 0) + 1 >= MAX_FAILS:
                # success, or too many failures: move on to the next post
                if result == 'ok':
                    count_push(post_label(selection))
                step += 1
                sub['step'] = step
                sub['fails'] = 0
                # next gap counts from the moment this push went out; no catch-up if we were offline
                sub['next_at'] = now_ts() + DRIP_DELAYS[step] if step < len(DRIP_DELAYS) else None
            else:
                sub['fails'] = sub.get('fails', 0) + 1
                sub['next_at'] = now_ts() + RETRY_SECONDS
            await asyncio.sleep(BROADCAST_DELAY)
        save()


# ---------------------------------------------------------------- conversions / PropellerAds S2S
_tasks = set()


def spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def propeller_url(kind, subid, payout):
    tpl = PROP_URL_REG if kind == 'reg' else PROP_URL_FTD
    if not tpl:
        return ''
    sub, pay = quote(str(subid), safe=''), quote(str(payout), safe='')
    return re.sub(r'\{(conversion_revenue|payout)\}', pay, re.sub(r'\{(external_id|visitor_id)\}', sub, tpl))


async def fire_propeller(user_id, kind, payout=None):
    """kind: 'reg' | 'ftd'. Sent at most once per user and kind. Never raises."""
    sub = state['subscribers'].get(str(user_id))
    if not sub or not sub.get('propeller_subid'):
        return 'no_subid'
    if sub.get(f'propeller_{kind}_at'):
        return 'already_sent'
    url = propeller_url(kind, sub['propeller_subid'], payout if payout not in (None, '') else PROP_PAYOUT[kind])
    if not url:
        return 'no_url'
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                ok = resp.status < 400
                status = 'sent' if ok else f'http_{resp.status}'
        log_event(user_id, 'propeller_postback', goal=kind, detail=f'{status} subid={sub["propeller_subid"]}')
        if ok:
            sub[f'propeller_{kind}_at'] = now_ts()
            save()
        return status
    except Exception as exc:
        logging.exception('Propeller %s failed', kind)
        log_event(user_id, 'propeller_postback', goal=kind, detail=f'error {exc}')
        return 'error'


def apply_conversion(user_id, kind, payout=None):
    """Mark reg / ftd for a user (postback or manual). Returns None for an unknown user, True if it was new."""
    sub = state['subscribers'].get(str(user_id))
    if not sub:
        return None
    field = f'{kind}_at'
    if sub.get(field):
        return False
    sub[field] = now_ts()
    if kind == 'ftd' and STOP_ON_FTD:
        sub['next_at'] = None  # the funnel's job is done: stop the push chain
    save()
    log_event(user_id, f'coinplay_{kind}', source=sub['first_source'])
    spawn(fire_propeller(user_id, kind, payout))
    return True


# ---------------------------------------------------------------- web: /r, /postback
async def h_root(_request):
    return web.Response(text='OK')


async def h_redirect(request):
    """Button click: count it (once per user and push), then send the user to the Mini App link with their id."""
    q = request.query
    if not (q.get('sub2') or '').isdigit():
        return web.Response(status=400, text='missing sub2')
    user_id = int(q['sub2'])
    placement = re.sub(r'[^A-Za-z0-9_-]', '', q.get('sub3') or '')[:24] or 'start'
    sub = state['subscribers'].get(str(user_id))
    if sub:
        first_here = placement not in sub['clicked_p']
        if first_here:
            sub['clicked_p'].append(placement)
        if not sub.get('clicked_at'):
            sub['clicked_at'] = now_ts()
        mark_dirty()
        log_event(user_id, 'offer_click', source=sub['first_source'], placement=placement,
                  detail='via /r' if first_here else 'via /r (repeat tap)')
    raise web.HTTPFound(target_url(user_id))


def record_postback(request, result, user_id=None):
    query = {k: ('***' if k == 'key' else v) for k, v in request.query.items()}
    append_jsonl(POSTBACKS_FILE, {'ts': now_ts(), 'result': result, 'user': user_id, 'query': query})


async def h_postback(request):
    q = request.query
    if POSTBACK_SECRET and q.get('key') != POSTBACK_SECRET:
        record_postback(request, 'rejected:bad_key')
        return web.json_response({'ok': False, 'error': 'forbidden'}, status=403)
    raw_id = (q.get('click_id') or q.get('subid') or '').strip()
    if not raw_id.isdigit():
        record_postback(request, 'rejected:missing_click_id')
        return web.json_response({'ok': False, 'error': 'missing click_id'}, status=400)
    user_id = int(raw_id)
    if q.get('test') == '1':  # connectivity check (/pbtest): logged, touches nothing
        record_postback(request, 'test', user_id)
        return web.json_response({'ok': True, 'test': True})
    status = (q.get('status') or '').lower()
    kind = 'ftd' if (status == 'ftd' or q.get('ftd')) else 'reg' if (status == 'reg' or q.get('reg')) else None
    if not kind:  # unknown shape: still logged, nothing lost
        record_postback(request, 'unrecognized', user_id)
        return web.json_response({'ok': True, 'ignored': True})
    result = apply_conversion(user_id, kind, q.get('payout') or q.get('amount') or q.get('revenue') or '')
    record_postback(request, f'{"unknown_user" if result is None else "ok"}:{kind}', user_id)
    logging.info('postback: %s user=%s new=%s', kind, user_id, result)
    return web.json_response({'ok': True})  # partners only check for a 2xx


def make_web_app():
    app = web.Application()
    app.router.add_get('/', h_root)
    app.router.add_get('/r', h_redirect)
    app.router.add_get('/postback/coinplay', h_postback)
    app.router.add_get('/postback', h_postback)
    return app


# ---------------------------------------------------------------- bot handlers
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):
    if message.chat.type != 'private' or not message.from_user:
        return
    register_start(message.from_user.id, message.from_user.username, command.args or '')
    await message.answer(WELCOME_TEXT)
    if not is_admin(message):
        return
    await message.answer(
        '🎰 Управление (ты тоже подписан и получаешь цепочку как пользователь)\n\n'
        '/posts — все 11 готовых баннеров\n'
        '/preview 9 — показать пост №9 только тебе (без номера — №1)\n'
        '/publish 9 — разово разослать пост №9 ВСЕМ подписчикам\n'
        '/setgames — настроить свои 3 игры\n'
        '/setimage — установить своё изображение\n'
        '/preview custom, /publish custom — свой пост\n'
        '/dripon и /dripoff — включить/приостановить цепочку у всех\n'
        '/dripnow — проверить цепочку на себе: следующий пуш придёт сразу\n\n'
        '/stats — старты, клики, reg, FTD по источникам (/stats full — всё)\n'
        '/status — подписчики, расписание, настройки\n'
        '/pbcheck, /pbtest — проверить постбэки\n'
        '/proppb, /proppb retry — PropellerAds S2S\n'
        '/markreg <id>, /markftd <id> [сумма] — отметить вручную')


@dp.message(Command('stop'))
async def stop(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    unsubscribe(message.from_user.id)
    await message.answer(STOP_TEXT)


@dp.my_chat_member()
async def on_member_update(event: ChatMemberUpdated):
    # Telegram tells us when a user blocks / unblocks the bot in a private chat.
    if event.chat.type != 'private':
        return
    if event.new_chat_member.status in ('kicked', 'left'):
        unsubscribe(event.chat.id)
    elif event.new_chat_member.status == 'member':
        subscribe(event.chat.id)


@dp.message(Command('posts'))
async def posts(message: Message):
    if not is_admin(message): return
    lines = [f'{i}. ' + ', '.join(g[0] for g in p['games']) for i, p in enumerate(PRESETS, 1)]
    await message.answer(f'Готовые публикации ({len(PRESETS)} постов):\n\n' + '\n'.join(lines))


@dp.message(Command('preview', 'publish'))
async def preview_or_publish(message: Message, bot: Bot):
    if not is_admin(message): return
    args = (message.text or '').partition(' ')[2].strip()
    cmd = message.text.split()[0].split('@')[0].lower()
    try:
        if cmd == '/preview':
            await send_post(bot, message.chat.id, resolve_selection(args))
        else:
            selection = resolve_selection(args, allow_empty=False)
            await message.answer(f'📤 Рассылка запущена, подписчиков: {len(active_items())}')
            sent, gone, failed = await broadcast(bot, selection)
            await message.answer(f'✅ Доставлено: {sent}\nОтписались/заблокировали бота: {gone}\nОшибок: {failed}')
    except Exception as exc:
        logging.exception('Publish / preview failed')
        await message.answer('Ошибка: ' + str(exc)[:400])


@dp.message(Command('setgames'))
async def setgames(message: Message):
    if not is_admin(message): return
    payload = (message.text or '').partition('\n')[2].strip()
    if not payload:
        await message.answer('Отправь одним сообщением:\n/setgames\nGolden Empire 1000 | 99.20\nSugar Rush | 98.99\nMental 2 | 97.05')
        return
    try:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]
        if len(lines) != 3: raise ValueError('Нужно ровно 3 игры')
        games = []
        for line in lines:
            if '|' not in line: raise ValueError(f'Нет разделителя "|" в строке: {line}')
            name, num = [s.strip() for s in line.rsplit('|', 1)]
            try:
                rtp = float(num.strip('%').replace(',', '.'))
            except ValueError:
                raise ValueError(f'RTP не число в строке: {line}') from None
            if not name or not 0 <= rtp <= 100: raise ValueError('Укажи имя и RTP от 0 до 100')
            games.append({'name': name, 'rtp': rtp})
        state['custom_games'] = games
        save()
        await message.answer('✅ Сохранено. Посмотри /preview custom')
    except ValueError as exc:
        await message.answer('Ошибка: ' + str(exc))


@dp.message(Command('setimage'))
async def setimage(message: Message):
    if not is_admin(message): return
    arg = (message.text or '').partition(' ')[2].strip()
    if arg:
        if not arg.startswith('https://'):
            await message.answer('Разрешены только https URL или фото с подписью /setimage')
            return
        state['custom_image'] = arg
        save()
        await message.answer('✅ Изображение сохранено. /preview custom')
    else:
        await message.answer('Пришли картинку как фото с подписью /setimage. Она будет использована для /preview custom и /publish custom.')


@dp.message(F.photo)
async def photo_handler(message: Message):
    if not is_admin(message): return
    if (message.caption or '').strip().lower().startswith('/setimage'):
        state['custom_image'] = message.photo[-1].file_id
        save()
        await message.answer('✅ Изображение сохранено. /preview custom')


@dp.message(Command('dripon', 'dripoff'))
async def drip_toggle(message: Message):
    if not is_admin(message): return
    state['drip_enabled'] = message.text.split()[0].split('@')[0].lower() == '/dripon'
    save()
    await message.answer('✅ Цепочка включена' if state['drip_enabled']
                         else '⏸ Цепочка на паузе у всех (таймеры продолжат идти, просроченные пуши уйдут после /dripon)')


@dp.message(Command('dripnow'))
async def drip_now(message: Message):
    if not is_admin(message): return
    sub, _ = ensure_subscriber(message.from_user.id)
    if sub['step'] >= len(DRIP_DELAYS):
        sub['step'] = 0  # chain finished: restart it on the admin for testing
    sub['next_at'] = now_ts()
    save()
    await message.answer(f'Следующий пуш (№{sub["step"] % len(PRESETS) + 1}) придёт в течение ~{TICK_SECONDS} сек.')


def pct(part, whole):
    return f'{part / whole * 100:.1f}' if whole else '0'


@dp.message(Command('stats'))
async def stats(message: Message):
    if not is_admin(message): return
    full = 'full' in (message.text or '').lower().split()[1:]
    users = list(state['subscribers'].values())
    unique = len(users)
    starts = sum(u['starts'] for u in users)
    active = sum(1 for u in users if u.get('active', True))
    clicked = sum(1 for u in users if u.get('clicked_at'))
    reg = sum(1 for u in users if u.get('reg_at'))
    ftd = sum(1 for u in users if u.get('ftd_at'))
    # per push: sent counter + users who tapped the button on that push (first tap per user and push)
    push_rows = []
    for label, sent in state['by_push'].items():
        clicks = sum(1 for u in users if label in u['clicked_p'])
        push_rows.append((label, sent, clicks))
    push_rows.sort(key=lambda r: (-r[2], -r[1]))
    shown_pushes = push_rows if full else [r for r in push_rows if r[1] >= 10 or r[2] > 0][:12]
    push_text = '\n'.join(f'  • {l}: {s} sent / {c} click ({pct(c, s)}%)' for l, s, c in shown_pushes) or '  (none)'
    # per source: first_source of the user
    by_src = {}
    for u in users:
        b = by_src.setdefault(u['first_source'], {'starts': 0, 'users': 0, 'click': 0, 'reg': 0, 'ftd': 0})
        b['starts'] += u['starts']
        b['users'] += 1
        b['click'] += 1 if u.get('clicked_at') else 0
        b['reg'] += 1 if u.get('reg_at') else 0
        b['ftd'] += 1 if u.get('ftd_at') else 0
    rows = sorted(by_src.items(), key=lambda kv: (-kv[1]['reg'], -kv[1]['starts']))
    visible = rows if full else [r for r in rows if r[1]['starts'] >= 5 or r[1]['reg'] or r[1]['ftd']][:12]
    hidden = len(rows) - len(visible)
    src_text = '\n'.join(f'  • {s}: {b["starts"]} start / {b["click"]} click / {b["reg"]} reg / {b["ftd"]} ftd' for s, b in visible) or '  (none)'
    text = (f'Funnel stats\n\n'
            f'Starts: {starts} ({unique} unique) · Active: {active} · Left/blocked: {unique - active}\n'
            f'Pushes sent: {state["pushes_sent"]} · Clicked: {clicked} users ({pct(clicked, unique)}%)\n'
            f'Reg: {reg} · FTD: {ftd}\n\n'
            f'Pushes{" (all)" if full else " (top)"}:\n{push_text}\n\n'
            f'Sources by first start (reg first{f", {hidden} small hidden" if hidden > 0 and not full else ""}):\n{src_text}'
            + ('' if full else '\n\n/stats full = everything'))
    await message.answer(text[:4000])  # Telegram rejects messages over 4096 chars


@dp.message(Command('status'))
async def status(message: Message):
    if not is_admin(message): return
    items = active_items()
    waiting = [v['next_at'] for _, v in items if v.get('next_at')]
    done = len(items) - len(waiting)
    nxt = human(min(waiting) - now_ts()) if waiting else '—'
    plan = ' → '.join(human(d) for d in DRIP_DELAYS)
    if TRACK_CLICKS:
        track = f'клики и постбэки через {PUBLIC_URL}'
    else:
        track = 'публичного домена нет: клики не считаются, постбэки не принимаются'
    await message.answer(f'Подписчиков: {len(items)} (в цепочке: {len(waiting)}, цепочка закончена/остановлена: {done})\n'
                         f'Цепочка: {"ON" if state["drip_enabled"] else "OFF (пауза)"}\n'
                         f'Ближайший пуш через: {nxt}\n'
                         f'Паузы: {plan}\n'
                         f'Кнопка → {MINIAPP_URL} (+{CLICK_PARAM}=id)\n'
                         f'Трекинг: {track}\n'
                         f'Propeller S2S: reg {"✓" if PROP_URL_REG else "—"} / ftd {"✓" if PROP_URL_FTD else "—"}\n'
                         f'Стоп цепочки после FTD: {"да" if STOP_ON_FTD else "нет"}\n'
                         f'Собственная картинка: {"да" if state["custom_image"] else "нет"}')


@dp.message(Command('pbcheck'))
async def pbcheck(message: Message):
    if not is_admin(message): return
    users = list(state['subscribers'].values())
    hits = read_jsonl_tail(POSTBACKS_FILE, 8)
    tail = '\n'.join(f'  {time.strftime("%d.%m %H:%M", time.gmtime(h["ts"]))} UTC  {h["result"]}  user={h.get("user")}' for h in hits) or '  (пока ни одного постбэка)'
    base = PUBLIC_URL or '(нет публичного домена — Railway → Settings → Networking → Generate Domain)'
    key = '&key=<POSTBACK_SECRET>' if POSTBACK_SECRET else ''
    await message.answer(
        f'Postback check\n\n'
        f'Клики через /r (юзеров): {sum(1 for u in users if u.get("clicked_at"))}\n'
        f'Юзеров с reg: {sum(1 for u in users if u.get("reg_at"))}\n'
        f'Юзеров с ftd: {sum(1 for u in users if u.get("ftd_at"))}\n\n'
        f'Последние постбэки:\n{tail}\n\n'
        f'URL постбэка для партнёрки:\n{base}/postback/coinplay\n'
        f'Reg: ?subid={{click_id}}&reg={{reg}}{key}  |  FTD: ?subid={{click_id}}&ftd={{ftd}}{key}  (status=reg|ftd тоже принимается)')


@dp.message(Command('pbtest'))
async def pbtest(message: Message):
    if not is_admin(message): return
    if not PUBLIC_URL:
        await message.answer('Нет публичного домена: Railway → Settings → Networking → Generate Domain.')
        return
    url = f'{PUBLIC_URL}/postback/coinplay?click_id={message.from_user.id}&status=reg&test=1'
    if POSTBACK_SECRET:
        url += f'&key={quote(POSTBACK_SECRET, safe="")}'
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                body = (await resp.text())[:200]
        await message.answer(f'Тестовый постбэк: HTTP {resp.status}\n{body}')
    except Exception as exc:
        await message.answer(f'Тестовый постбэк не дошёл: {exc}')


@dp.message(Command('proppb'))
async def proppb(message: Message):
    if not is_admin(message): return
    retry = 'retry' in (message.text or '').lower().split()[1:]
    users = {k: u for k, u in state['subscribers'].items() if u.get('propeller_subid')}
    lines = []
    if retry:
        for k, u in users.items():
            for kind in ('reg', 'ftd'):
                if u.get(f'{kind}_at') and not u.get(f'propeller_{kind}_at'):
                    lines.append(f'{k} {kind}: {await fire_propeller(int(k), kind)}')
    c = lambda field: sum(1 for u in users.values() if u.get(field))
    text = (f'PropellerAds S2S\nURL reg: {"set" if PROP_URL_REG else "NOT set"} | URL ftd: {"set" if PROP_URL_FTD else "NOT set"}\n'
            f'Users with SUBID: {len(users)}\nRegs: {c("reg_at")} → sent {c("propeller_reg_at")}\n'
            f'FTDs: {c("ftd_at")} → sent {c("propeller_ftd_at")}')
    if retry:
        text += '\n\nRetry:\n' + ('\n'.join(lines[:30]) or '(nothing to resend)')
    else:
        text += '\n\n/proppb retry — resend every reg/ftd that has a SUBID but was not delivered'
    text += f'\nLast SUBIDs: {", ".join(u["propeller_subid"] for u in list(users.values())[-3:]) or "-"}'
    await message.answer(text[:4000])


@dp.message(Command('markreg', 'markftd'))
async def mark_manual(message: Message):
    """For when the partner postback is not firing: /markreg 123 456, /markftd 123 [payout]."""
    if not is_admin(message): return
    parts = (message.text or '').split()
    kind = 'ftd' if parts[0].split('@')[0].lower() == '/markftd' else 'reg'
    args = parts[1:]
    if not args or not args[0].isdigit():
        await message.answer('Пример: /markftd 123456789 [сумма]' if kind == 'ftd' else 'Пример: /markreg 123456789 987654321')
        return
    if kind == 'ftd':
        ids, payout = [args[0]], (args[1] if len(args) > 1 else None)
    else:
        ids, payout = [a for a in args if a.isdigit()], None
    out = []
    for uid in ids:
        res = apply_conversion(int(uid), kind, payout)
        sub = state['subscribers'].get(uid)
        extra = f' (propeller: {"subid есть, отправляю" if sub and sub.get("propeller_subid") else "нет subid"})' if res else ''
        out.append(f'{uid}: ' + ('нет такого пользователя' if res is None else 'уже было отмечено' if res is False else f'отмечено {kind}' + extra))
    await message.answer('\n'.join(out))


async def scheduler(bot: Bot):
    while True:
        try:
            await drip_tick(bot)
            if _dirty:
                save()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let the scheduler die silently (e.g. disk error or Telegram error).
            logging.exception('Scheduler tick failed')
        await asyncio.sleep(TICK_SECONDS)


async def main():
    if not ADMIN_IDS: raise RuntimeError('ADMIN_IDS must not be empty')
    if not MINIAPP_URL.startswith('https://'): raise RuntimeError('MINIAPP_URL must start with https://')
    if not IS_TME and not PUBLIC_URL:
        logging.warning('MINIAPP_URL не t.me-ссылка и нет публичного домена: ссылка будет открываться как есть')
    if not PUBLIC_URL:
        logging.warning('Нет PUBLIC_URL / RAILWAY_PUBLIC_DOMAIN: клики не считаются, постбэки принять некуда. '
                        'Railway → Settings → Networking → Generate Domain')
    if not POSTBACK_SECRET:
        logging.warning('POSTBACK_SECRET не задан: любой, кто знает URL, может отправить фейковый reg/ftd')
    runner = web.AppRunner(make_web_app())
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logging.info('Web server on :%s (public: %s)', PORT, PUBLIC_URL or '-')
    try:
        async with Bot(BOT_TOKEN) as bot:
            task = asyncio.create_task(scheduler(bot))
            try:
                await bot.delete_webhook(drop_pending_updates=False)
                await dp.start_polling(bot)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if _dirty:
                    save()
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
