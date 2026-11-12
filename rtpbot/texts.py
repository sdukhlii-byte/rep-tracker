"""All user-facing copy (English)."""
from __future__ import annotations

from html import escape as _escape

from .data import Catalog, Slot


def escape(text: str) -> str:
    # Keep apostrophes and quotes as-is; Telegram HTML only needs & < >.
    return _escape(text, quote=False)


BOT_DESCRIPTION = (
    "RTP Tracker — the published return-to-player, volatility and house-edge "
    "figures for popular slots across the major game providers.\n\n"
    "RTP · volatility · house edge — by the numbers.\n\n"
    "Tap /start to open."
)
BOT_SHORT_DESCRIPTION = "Published RTP, volatility and house edge for popular slots."

DISCLAIMER = (
    "<i>RTP is a long-run theoretical average, not a prediction for any session. "
    "Casinos choose which RTP build to run, so check the game's info screen. 18+</i>"
)

CONF_LABEL = {
    "multi": "✅ Matches across 2+ public sources",
    "single": "☝️ Only one public source found",
    "conflict": "⚠️ Public sources disagree",
}


def welcome(cat: Catalog) -> str:
    return (
        "🎰 <b>RTP Tracker — Slot Analytics</b>\n\n"
        f"Published RTP, volatility and house edge for <b>{len(cat.slots)}</b> popular slots "
        f"from <b>{len(cat.providers)}</b> providers.\n\n"
        "Pick a section below, or just type a slot name to look it up."
    )


def about(cat: Catalog) -> str:
    return (
        "ℹ️ <b>How to read the numbers</b>\n\n"
        "<b>RTP</b> (return to player) is the share of all stakes a game pays back "
        "on average over a very large number of spins. 96% RTP means 96 back per 100 staked.\n\n"
        "<b>House edge</b> is the other side: 100% − RTP.\n\n"
        "<b>Volatility</b> describes how that return is distributed. Low volatility means "
        "frequent small wins, high means long dry spells and rare big hits. It says nothing "
        "about RTP.\n\n"
        "<b>RTP builds.</b> Many games are certified at several RTP levels and the casino picks one. "
        "The same slot can have a house edge several times higher at one casino than at another, "
        "so always check the in-game info screen.\n\n"
        "<b>No predictions.</b> Slots are random. Nothing here tells you which game is "
        "\"hot\" or \"due\".\n\n"
        f"<b>Sources.</b> Figures are compiled from public game-info and review pages and cross-checked "
        f"where possible; each card shows how well the sources agree. Updated {escape(cat.updated)}.\n\n"
        "18+ · Play responsibly."
    )


def fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def slot_card(s: Slot) -> str:
    lines = [
        f"🎰 <b>{escape(s.name)}</b>",
        f"<i>{escape(s.provider)}</i>",
        "",
    ]
    if s.conf == "conflict" and s.range:
        lines.append(f"RTP: <b>~{fmt_pct(s.rtp)}</b> (range {fmt_pct(s.range[0])}–{fmt_pct(s.range[1])})")
        lines.append(f"House edge: <b>~{fmt_pct(s.house_edge)}</b>")
    else:
        lines.append(f"RTP: <b>{fmt_pct(s.rtp)}</b>")
        lines.append(f"House edge: <b>{fmt_pct(s.house_edge)}</b>")
    lines.append(f"Volatility: <b>{escape(s.vol) if s.vol else 'n/a'}</b>")

    if s.alt:
        lowest = min(s.alt)
        builds = " · ".join(fmt_pct(a) for a in s.alt)
        lines += [
            "",
            f"Other RTP builds reported: {builds}",
            f"At {fmt_pct(lowest)} the house edge is {fmt_pct(100 - lowest)}.",
        ]
    if s.note:
        lines += ["", f"Note: {escape(s.note)}"]
    lines += ["", CONF_LABEL.get(s.conf, ""), "", DISCLAIMER]
    return "\n".join(lines)


def slot_line(s: Slot) -> str:
    mark = {"multi": "", "single": " ☝️", "conflict": " ⚠️"}[s.conf]
    return f"{s.name} · {s.rtp:.2f}%{mark}"


def top_rtp(slots: list[Slot]) -> str:
    rows = []
    for i, s in enumerate(slots, 1):
        mark = {"multi": "", "single": " ☝️", "conflict": " ⚠️"}[s.conf]
        vol = s.vol or "n/a"
        rows.append(
            f"{i}. <b>{escape(s.name)}</b> — {s.rtp:.2f}%{mark}\n"
            f"    {escape(s.provider)} · {escape(vol)}"
        )
    return (
        "🏆 <b>Highest published RTP</b>\n\n"
        + "\n".join(rows)
        + "\n\n☝️ one source only · ⚠️ sources disagree\n"
        "A higher RTP doesn't mean smaller swings; check volatility too.\n\n"
        + DISCLAIMER
    )


def provider_header(provider: str, count: int, page: int, pages: int) -> str:
    tail = f" · page {page + 1}/{pages}" if pages > 1 else ""
    return f"🏢 <b>{escape(provider)}</b> — {count} slots{tail}\n\nTap a slot to see its numbers."


def vol_header(level: str, count: int, page: int, pages: int) -> str:
    tail = f" · page {page + 1}/{pages}" if pages > 1 else ""
    return f"🌪 <b>{escape(level)} volatility</b> — {count} slots{tail}\n\nSorted by RTP, highest first."


def search_none(query: str) -> str:
    return (
        f"Nothing found for «{escape(query[:40])}».\n"
        "Try part of the name (for example <code>bonanza</code> or <code>book of</code>) "
        "or browse by provider."
    )


def search_many(query: str) -> str:
    return f"🔎 Results for «{escape(query[:40])}»:"
