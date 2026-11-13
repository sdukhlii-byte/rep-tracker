"""Telegram push-broadcast bot: sends banner posts with a Mini App button to subscribers. Python 3.11+, aiogram 3."""
import asyncio
import copy
import html
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def parse_post_times(raw):
    """'9:00, 15:30' -> ['09:00', '15:30']; fails loudly on a bad value."""
    times = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', part)
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise RuntimeError(f'POST_TIMES: неверное время "{part}", нужен формат ЧЧ:ММ')
        times.append(f'{int(m[1]):02d}:{m[2]}')
    return times


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
TZ = ZoneInfo(env('TIMEZONE', 'Europe/Madrid'))
POST_TIMES = parse_post_times(env('POST_TIMES', '10:00,15:00'))
DATA_FILE = Path(env('DATA_FILE', str(ROOT / 'data.json')))

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
    'next_index': 0,
    'subscribers': [],
    'auto': False,
    'posted_minutes': [],
    'custom_image': '',
    'custom_games': [
        {'name': 'Golden Empire 1000', 'rtp': 99.20},
        {'name': 'Sugar Rush', 'rtp': 98.99},
        {'name': 'Mental 2', 'rtp': 97.05},
    ],
}

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
    return data

state = load_data()

def save():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DATA_FILE)

def is_admin(message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_IDS and message.chat.type == 'private')

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
    # web_app buttons do NOT work in channel posts, a direct Mini App link does.
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=BUTTON_TEXT, url=MINIAPP_URL)
    ]])

def resolve_selection(text):
    """Accept a 1-based preset index or 'custom'; default is next rotation preset."""
    arg = text.strip().lower()
    if arg == 'custom':
        return ('custom', state['custom_games'], state['custom_image'])
    if arg:
        if not arg.isdigit():
            raise ValueError(f'Укажи номер от 1 до {len(PRESETS)} или custom')
        idx = int(arg) - 1
        if not 0 <= idx < len(PRESETS):
            raise ValueError(f'Номер должен быть от 1 до {len(PRESETS)}')
    else:
        idx = state['next_index'] % len(PRESETS)
    preset = PRESETS[idx]
    return (idx, preset['games'], str(ASSETS / preset['image']))

def local_file(img):
    try:
        return Path(img).is_file()
    except (OSError, ValueError):  # file_id / long URL can't be a path
        return False

photo_cache = {}  # banner -> Telegram file_id, so each banner is uploaded once, not once per subscriber
broadcast_lock = asyncio.Lock()
BROADCAST_DELAY = 0.05  # ~20 msgs/sec, safely below Telegram's ~30/sec limit

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

def advance(selection):
    if isinstance(selection[0], int):
        state['next_index'] = (selection[0] + 1) % len(PRESETS)
        save()

def subscribe(user_id):
    if user_id not in state['subscribers']:
        state['subscribers'].append(user_id)
        save()

def unsubscribe(user_id):
    if user_id in state['subscribers']:
        state['subscribers'].remove(user_id)
        save()

async def broadcast(bot, selection):
    """Push one post to every subscriber. Returns (sent, gone, failed)."""
    async with broadcast_lock:
        sent = gone = failed = streak = 0
        for uid in list(state['subscribers']):
            try:
                try:
                    await send_post(bot, uid, selection)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    await send_post(bot, uid, selection)
                sent += 1
                streak = 0
            except TelegramForbiddenError:  # user blocked the bot / account deleted
                unsubscribe(uid)
                gone += 1
            except TelegramBadRequest as exc:
                if 'chat not found' in str(exc).lower():
                    unsubscribe(uid)
                    gone += 1
                else:
                    failed += 1
                    streak += 1
                    logging.error('Send to %s failed: %s', uid, exc)
            except Exception:
                failed += 1
                streak += 1
                logging.exception('Send to %s failed', uid)
            if streak >= 5:  # same error for everyone (bad banner / URL) -> stop instead of spamming logs
                logging.error('Broadcast aborted after %s consecutive errors', streak)
                break
            await asyncio.sleep(BROADCAST_DELAY)
        if sent:
            advance(selection)
        return sent, gone, failed

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
        '🎰 Управление рассылкой (ты тоже подписан, посты придут и тебе)\n\n'
        '/posts — все 11 готовых баннеров\n'
        '/preview — предпросмотр следующего (только тебе)\n'
        '/preview 11 — предпросмотр №11\n'
        '/publish — разослать следующий ВСЕМ подписчикам и перейти к следующему\n'
        '/publish 11 — разослать №11\n'
        '/setgames — настроить свои 3 игры\n'
        '/setimage — установить своё изображение\n'
        '/preview custom — посмотреть свой пост\n'
        '/publish custom — разослать свой пост\n'
        '/autoon и /autooff — включить/выключить расписание\n'
        '/status — настройки и число подписчиков')

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
    lines = [f'{i}. ' + ', '.join(g[0] for g in p['games']) for i,p in enumerate(PRESETS, 1)]
    await message.answer(f'Готовые публикации ({len(PRESETS)} постов):\n\n' + '\n'.join(lines))

@dp.message(Command('preview', 'publish'))
async def preview_or_publish(message: Message, bot: Bot):
    if not is_admin(message): return
    args = (message.text or '').partition(' ')[2].strip()
    cmd = message.text.split()[0].split('@')[0].lower()
    try:
        selection = resolve_selection(args)
        if cmd == '/preview':
            await send_post(bot, message.chat.id, selection)
        else:
            total = len(state['subscribers'])
            await message.answer(f'📤 Рассылка запущена, подписчиков: {total}')
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

@dp.message(Command('autoon', 'autooff'))
async def auto_handler(message: Message):
    if not is_admin(message): return
    state['auto'] = message.text.split()[0].split('@')[0].lower() == '/autoon'
    save()
    await message.answer(('✅ Авторассылка активна: ' + ', '.join(POST_TIMES) + f' ({TZ.key})') if state['auto'] else '⏸ Авторассылка отключена')

@dp.message(Command('status'))
async def status(message: Message):
    if not is_admin(message): return
    await message.answer(f'Подписчиков: {len(state["subscribers"])}\nКнопка → {MINIAPP_URL}\nАвторассылка: {"ON" if state["auto"] else "OFF"}\n'
                         f'Часы: {", ".join(POST_TIMES)} ({TZ.key})\n'
                         f'Следующий баннер: {state["next_index"] % len(PRESETS) + 1}\n'
                         f'Собственная картинка: {"да" if state["custom_image"] else "нет"}')

async def scheduler(bot: Bot):
    while True:
        try:
            now = datetime.now(TZ)
            key = now.strftime('%Y-%m-%d %H:%M')
            if state['auto'] and now.strftime('%H:%M') in POST_TIMES and key not in state['posted_minutes']:
                # Persist timestamp before send; prevents duplicate spam on crash / restart.
                state['posted_minutes'].append(key)
                state['posted_minutes'] = state['posted_minutes'][-60:]
                save()
                sent, gone, failed = await broadcast(bot, resolve_selection(''))
                logging.info('Scheduled broadcast %s: sent=%s gone=%s failed=%s', key, sent, gone, failed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let the scheduler die silently (e.g. disk error or Telegram error).
            logging.exception('Scheduled broadcast failed')
        await asyncio.sleep(15)

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
