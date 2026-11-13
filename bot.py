"""Telegram drip-push bot: every subscriber gets banner posts (with a Mini App button)
on a personal schedule counted from the moment they pressed /start. Python 3.11+, aiogram 3."""
import asyncio
import copy
import html
import json
import logging
import os
import re
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
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
BUTTON_TEXT = env('BUTTON_TEXT', '🎰 PLAY NOW!')
WELCOME_TEXT = env('WELCOME_TEXT', '✅ You are subscribed! The top slots by RTP will arrive right here. Send /stop to unsubscribe.')
STOP_TEXT = env('STOP_TEXT', '⏸ Unsubscribed. Send /start to subscribe again.')
# Pause before the 1st push (counted from /start), then the pause after each push before the next one.
# One entry = one push. Posts go in the order 1..11 and cycle if there are more than 11 entries.
DRIP_DELAYS = parse_delays(env('DRIP_DELAYS', '15m,2h,5h,12h,20h,1d,2d,3d,4d,5d,7d'))
DATA_FILE = Path(env('DATA_FILE', str(ROOT / 'data.json')))

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
    # user_id (as str) -> {'joined': ts, 'step': pushes already sent, 'next_at': ts or None, 'fails': n}
    'subscribers': {},
    'drip_enabled': True,
    'custom_image': '',
    'custom_games': [
        {'name': 'Golden Empire 1000', 'rtp': 99.20},
        {'name': 'Sugar Rush', 'rtp': 98.99},
        {'name': 'Mental 2', 'rtp': 97.05},
    ],
}


def now_ts():
    return int(time.time())


def load_data():
    # deepcopy: DEFAULT holds lists/dicts, a shallow copy would let runtime changes leak into it.
    data = copy.deepcopy(DEFAULT)
    if not DATA_FILE.exists():
        return data
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
    return data


def new_sub():
    return {'joined': now_ts(), 'step': 0, 'next_at': now_ts() + DRIP_DELAYS[0], 'fails': 0}


state = load_data()


def save():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DATA_FILE)


def is_admin(message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_IDS and message.chat.type == 'private')


def subscribe(user_id):
    key = str(user_id)
    if key not in state['subscribers']:
        state['subscribers'][key] = new_sub()
        save()


def unsubscribe(user_id, persist=True):
    if state['subscribers'].pop(str(user_id), None) is not None and persist:
        save()


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


def keyboard():
    # A plain URL button with a t.me Mini App link (https://t.me/<bot>/<app>[?startapp=...]).
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=BUTTON_TEXT, url=MINIAPP_URL)
    ]])


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
    if img:
        cached = photo_cache.get(img)
        photo = cached or (FSInputFile(img) if local_file(img) else img)
        msg = await bot.send_photo(chat_id, photo, caption=caption, parse_mode='HTML', reply_markup=keyboard())
        if not cached and msg.photo:
            photo_cache[img] = msg.photo[-1].file_id
        return msg
    return await bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=keyboard())


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


async def broadcast(bot, selection):
    """Manual push of one post to every subscriber. Returns (sent, gone, failed)."""
    async with send_lock:
        sent = gone = failed = streak = 0
        for key in list(state['subscribers']):
            result = await safe_send(bot, int(key), selection)
            if result == 'ok':
                sent += 1
                streak = 0
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
    due = [k for k, v in state['subscribers'].items() if v.get('next_at') and v['next_at'] <= now]
    if not due:
        return
    async with send_lock:
        for key in due:
            sub = state['subscribers'].get(key)
            if not sub:
                continue
            step = sub['step']
            result = await safe_send(bot, int(key), preset_selection(step % len(PRESETS)))
            if result == 'gone':
                state['subscribers'].pop(key, None)
            elif result == 'ok' or sub.get('fails', 0) + 1 >= MAX_FAILS:
                # success, or too many failures: move on to the next post
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


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    subscribe(message.from_user.id)
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
        '/dripnow — проверить цепочку на себе: следующий пуш придёт сразу\n'
        '/status — подписчики и расписание цепочки')


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
            await message.answer(f'📤 Рассылка запущена, подписчиков: {len(state["subscribers"])}')
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
    subscribe(message.from_user.id)
    sub = state['subscribers'][str(message.from_user.id)]
    if sub['step'] >= len(DRIP_DELAYS):
        sub['step'] = 0  # chain finished: restart it on the admin for testing
    sub['next_at'] = now_ts()
    save()
    await message.answer(f'Следующий пуш (№{sub["step"] % len(PRESETS) + 1}) придёт в течение ~{TICK_SECONDS} сек.')


@dp.message(Command('status'))
async def status(message: Message):
    if not is_admin(message): return
    subs = state['subscribers']
    waiting = [v['next_at'] for v in subs.values() if v.get('next_at')]
    done = sum(1 for v in subs.values() if not v.get('next_at'))
    nxt = f'{human(min(waiting) - now_ts())}' if waiting else '—'
    plan = ' → '.join(human(d) for d in DRIP_DELAYS)
    await message.answer(f'Подписчиков: {len(subs)} (в цепочке: {len(waiting)}, прошли все пуши: {done})\n'
                         f'Цепочка: {"ON" if state["drip_enabled"] else "OFF (пауза)"}\n'
                         f'Ближайший пуш через: {nxt}\n'
                         f'Паузы: {plan}\n'
                         f'Кнопка → {MINIAPP_URL}\n'
                         f'Собственная картинка: {"да" if state["custom_image"] else "нет"}')


async def scheduler(bot: Bot):
    while True:
        try:
            await drip_tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let the scheduler die silently (e.g. disk error or Telegram error).
            logging.exception('Drip tick failed')
        await asyncio.sleep(TICK_SECONDS)


async def main():
    if not ADMIN_IDS: raise RuntimeError('ADMIN_IDS must not be empty')
    if not MINIAPP_URL.startswith('https://'): raise RuntimeError('MINIAPP_URL must start with https://')
    if not re.match(r'https://(t|telegram)\.me/', MINIAPP_URL):
        logging.warning('MINIAPP_URL не похож на ссылку t.me/<bot>/<app> — кнопка откроет обычный браузер, а не Mini App')
    async with Bot(BOT_TOKEN) as bot:
        task = asyncio.create_task(scheduler(bot))
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
