"""Slot catalog: loading, lookup, search and rankings."""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "slots.json"

# Order used for the volatility filter.
VOL_LEVELS = ["Low", "Low-Medium", "Medium", "Medium-High", "High", "Very High"]


@dataclass(frozen=True)
class Slot:
    id: str
    name: str
    provider: str
    rtp: float
    vol: str | None = None
    alt: tuple[float, ...] = ()
    conf: str = "single"  # multi | single | conflict
    range: tuple[float, float] | None = None
    note: str | None = None
    jackpot: bool = False

    @property
    def house_edge(self) -> float:
        return round(100 - self.rtp, 2)


@dataclass
class Catalog:
    slots: list[Slot]
    updated: str
    by_id: dict[str, Slot] = field(init=False)
    providers: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {s.id: s for s in self.slots}
        # Providers with the most slots first, then alphabetical.
        counts: dict[str, int] = {}
        for s in self.slots:
            counts[s.provider] = counts.get(s.provider, 0) + 1
        self.providers = sorted(counts, key=lambda p: (-counts[p], p))

    def by_provider(self, provider: str) -> list[Slot]:
        return sorted((s for s in self.slots if s.provider == provider), key=lambda s: s.name)

    def by_volatility(self, level: str) -> list[Slot]:
        return sorted((s for s in self.slots if s.vol == level), key=lambda s: (-s.rtp, s.name))

    def vol_counts(self) -> dict[str, int]:
        return {lv: sum(1 for s in self.slots if s.vol == lv) for lv in VOL_LEVELS}

    def top_rtp(self, n: int = 10) -> list[Slot]:
        return sorted(self.slots, key=lambda s: (-s.rtp, s.name))[:n]

    def search(self, query: str, limit: int = 8) -> list[Slot]:
        q = _norm(query)
        if len(q) < 2:
            return []
        scored: list[tuple[float, Slot]] = []
        q_tokens = set(q.split())
        for s in self.slots:
            n = _norm(s.name)
            hay = f"{n} {_norm(s.provider)}"
            if q == n:
                score = 3.0
            elif q in n:
                score = 2.0 + len(q) / len(n)
            elif q in hay:
                score = 1.5
            elif q_tokens and q_tokens <= set(hay.split()):
                score = 1.4
            else:
                score = difflib.SequenceMatcher(None, q, n).ratio()
                if score < 0.62:
                    continue
            scored.append((score, s))
        scored.sort(key=lambda t: (-t[0], t[1].name))
        return [s for _, s in scored[:limit]]


def _norm(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def load_catalog(path: Path = DATA_FILE) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    slots = [
        Slot(
            id=d["id"],
            name=d["name"],
            provider=d["provider"],
            rtp=float(d["rtp"]),
            vol=d.get("vol"),
            alt=tuple(d.get("alt", ())),
            conf=d.get("conf", "single"),
            range=tuple(d["range"]) if d.get("range") else None,
            note=d.get("note"),
            jackpot=bool(d.get("jackpot", False)),
        )
        for d in raw["slots"]
    ]
    return Catalog(slots=slots, updated=raw["updated"])
