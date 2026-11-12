"""Telegram handlers."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from . import keyboards as kb
from . import texts
from .data import VOL_LEVELS, Catalog

log = logging.getLogger(__name__)


def build_router(cat: Catalog) -> Router:
    r = Router()

    async def show(cb: CallbackQuery, text: str, markup) -> None:
        """Edit the message in place; ignore the 'not modified' error on repeated taps."""
        try:
            await cb.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        await cb.answer()

    # ---- commands ----------------------------------------------------------
    @r.message(CommandStart())
    @r.message(Command("menu"))
    async def start(m: Message) -> None:
        await m.answer(texts.welcome(cat), reply_markup=kb.main_menu())

    @r.message(Command("about"))
    async def about_cmd(m: Message) -> None:
        await m.answer(texts.about(cat), reply_markup=kb.home_only())

    @r.message(Command("top"))
    async def top_cmd(m: Message) -> None:
        await m.answer(texts.top_rtp(cat.top_rtp(10)), reply_markup=kb.home_only())

    # ---- navigation callbacks ---------------------------------------------
    @r.callback_query(F.data == "home")
    async def home(cb: CallbackQuery) -> None:
        await show(cb, texts.welcome(cat), kb.main_menu())

    @r.callback_query(F.data == "about")
    async def about(cb: CallbackQuery) -> None:
        await show(cb, texts.about(cat), kb.home_only())

    @r.callback_query(F.data == "top")
    async def top(cb: CallbackQuery) -> None:
        await show(cb, texts.top_rtp(cat.top_rtp(10)), kb.home_only())

    @r.callback_query(F.data == "provs")
    async def provs(cb: CallbackQuery) -> None:
        await show(cb, "🏢 <b>Choose a provider</b>", kb.providers_menu(cat))

    @r.callback_query(F.data == "vols")
    async def vols(cb: CallbackQuery) -> None:
        await show(
            cb,
            "🌪 <b>Choose a volatility level</b>\n\nVolatility is how uneven the payouts are, not how much is paid back.",
            kb.volatility_menu(cat),
        )

    @r.callback_query(F.data.startswith("p:"))
    async def provider_page(cb: CallbackQuery) -> None:
        try:
            _, idx, page = cb.data.split(":")
            provider = cat.providers[int(idx)]
            page = int(page)
        except (ValueError, IndexError):
            await cb.answer("Outdated button, open the menu again.", show_alert=True)
            return
        slots = cat.by_provider(provider)
        page = min(max(page, 0), kb.pages_for(len(slots)) - 1)
        await show(
            cb,
            texts.provider_header(provider, len(slots), page, kb.pages_for(len(slots))),
            kb.slot_list(slots, page, f"p:{idx}", back="provs"),
        )

    @r.callback_query(F.data.startswith("v:"))
    async def vol_page(cb: CallbackQuery) -> None:
        try:
            _, idx, page = cb.data.split(":")
            level = VOL_LEVELS[int(idx)]
            page = int(page)
        except (ValueError, IndexError):
            await cb.answer("Outdated button, open the menu again.", show_alert=True)
            return
        slots = cat.by_volatility(level)
        page = min(max(page, 0), kb.pages_for(len(slots)) - 1)
        await show(
            cb,
            texts.vol_header(level, len(slots), page, kb.pages_for(len(slots))),
            kb.slot_list(slots, page, f"v:{idx}", back="vols"),
        )

    @r.callback_query(F.data.startswith("s:"))
    async def slot(cb: CallbackQuery) -> None:
        s = cat.by_id.get(cb.data[2:])
        if s is None:
            await cb.answer("Slot not found.", show_alert=True)
            return
        await show(cb, texts.slot_card(s), kb.slot_card(s, cat.providers.index(s.provider)))

    # ---- free-text search --------------------------------------------------
    @r.message(F.text & ~F.text.startswith("/"))
    async def search(m: Message) -> None:
        query = m.text.strip()
        found = cat.search(query)
        if not found:
            await m.answer(texts.search_none(query), reply_markup=kb.main_menu())
        elif len(found) == 1 or _exact(found[0].name, query):
            s = found[0]
            await m.answer(texts.slot_card(s), reply_markup=kb.slot_card(s, cat.providers.index(s.provider)))
        else:
            await m.answer(texts.search_many(query), reply_markup=kb.search_results(found))

    return r


def _exact(name: str, query: str) -> bool:
    norm = lambda t: "".join(ch for ch in t.lower() if ch.isalnum())  # noqa: E731
    return norm(name) == norm(query)
