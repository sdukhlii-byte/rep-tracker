"""Inline keyboards. Callback data stays well under Telegram's 64-byte limit."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Markup

from .data import VOL_LEVELS, Catalog, Slot
from .texts import slot_line

PAGE_SIZE = 8

HOME = Btn(text="🏠 Menu", callback_data="home")


def _grid(buttons: list[Btn], per_row: int) -> list[list[Btn]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def pages_for(total: int) -> int:
    return max(1, -(-total // PAGE_SIZE))


def main_menu() -> Markup:
    return Markup(
        inline_keyboard=_grid(
            [
                Btn(text="🏢 By provider", callback_data="provs"),
                Btn(text="🏆 Top RTP", callback_data="top"),
                Btn(text="🌪 By volatility", callback_data="vols"),
                Btn(text="ℹ️ How to read RTP", callback_data="about"),
            ],
            2,
        )
    )


def providers_menu(cat: Catalog) -> Markup:
    btns = [
        Btn(text=f"{p} ({len(cat.by_provider(p))})", callback_data=f"p:{i}:0")
        for i, p in enumerate(cat.providers)
    ]
    return Markup(inline_keyboard=[*_grid(btns, 2), [HOME]])


def volatility_menu(cat: Catalog) -> Markup:
    counts = cat.vol_counts()
    btns = [
        Btn(text=f"{lv} ({counts[lv]})", callback_data=f"v:{i}:0")
        for i, lv in enumerate(VOL_LEVELS)
        if counts[lv]
    ]
    return Markup(inline_keyboard=[*_grid(btns, 2), [HOME]])


def slot_list(slots: list[Slot], page: int, prefix: str, back: str) -> Markup:
    """Paginated slot list. `prefix` like 'p:3' produces page callbacks 'p:3:<n>'.
    `back` is 'provs' or 'vols'."""
    start = page * PAGE_SIZE
    rows = [[Btn(text=slot_line(s), callback_data=f"s:{s.id}")] for s in slots[start : start + PAGE_SIZE]]
    nav = []
    if page > 0:
        nav.append(Btn(text="◀️ Prev", callback_data=f"{prefix}:{page - 1}"))
    if page < pages_for(len(slots)) - 1:
        nav.append(Btn(text="Next ▶️", callback_data=f"{prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    label = "◀️ Providers" if back == "provs" else "◀️ Volatility"
    rows.append([Btn(text=label, callback_data=back), HOME])
    return Markup(inline_keyboard=rows)


def slot_card(s: Slot, provider_idx: int | None) -> Markup:
    rows = []
    if provider_idx is not None:
        rows.append([Btn(text=f"◀️ More from {s.provider}", callback_data=f"p:{provider_idx}:0")])
    rows.append([HOME])
    return Markup(inline_keyboard=rows)


def search_results(slots: list[Slot]) -> Markup:
    rows = [[Btn(text=slot_line(s), callback_data=f"s:{s.id}")] for s in slots]
    rows.append([HOME])
    return Markup(inline_keyboard=rows)


def home_only() -> Markup:
    return Markup(inline_keyboard=[[HOME]])
