import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from rtpbot import keyboards as kb
from rtpbot import texts
from rtpbot.data import VOL_LEVELS, load_catalog

cat = load_catalog()


def test_ids_unique_and_fields_sane():
    ids = [s.id for s in cat.slots]
    assert len(ids) == len(set(ids))
    for s in cat.slots:
        assert 80 <= s.rtp <= 100, s.name
        assert s.vol is None or s.vol in VOL_LEVELS, (s.name, s.vol)
        assert s.conf in {"multi", "single", "conflict"}
        if s.conf == "conflict":
            assert s.range and s.range[0] <= s.rtp <= s.range[1], s.name
        assert all(0 < a < s.rtp + 3 for a in s.alt), s.name


def test_house_edge():
    s = cat.by_id["book-of-dead"]
    assert s.house_edge == 3.79


def test_callback_data_under_limit():
    for s in cat.slots:
        assert len(f"s:{s.id}".encode()) <= 64
    for p in cat.providers:
        markup = kb.slot_list(cat.by_provider(p), 0, "p:99", "provs")
        for row in markup.inline_keyboard:
            for b in row:
                assert len(b.callback_data.encode()) <= 64


def test_pagination_covers_all_slots():
    p = cat.providers[0]
    slots = cat.by_provider(p)
    seen = []
    for page in range(kb.pages_for(len(slots))):
        m = kb.slot_list(slots, page, "p:0", "provs")
        seen += [b.callback_data for row in m.inline_keyboard for b in row if b.callback_data.startswith("s:")]
    assert len(seen) == len(slots)


@pytest.mark.parametrize(
    "q,expected",
    [
        ("book of dead", "book-of-dead"),
        ("gonzo", "gonzos-quest"),
        ("Gonzos Quest", "gonzos-quest"),
        ("razor shrak", "razor-shark"),
        ("mega moolah", "mega-moolah"),
    ],
)
def test_search_top_hit(q, expected):
    assert cat.search(q)[0].id == expected


def test_search_junk_and_short():
    assert cat.search("zzzzzz") == []
    assert cat.search("a") == []


def test_search_provider_name():
    res = cat.search("hacksaw")
    assert res and all(s.provider == "Hacksaw Gaming" for s in res)


def test_top_rtp_sorted():
    top = cat.top_rtp(10)
    assert [s.rtp for s in top] == sorted((s.rtp for s in top), reverse=True)


def test_texts_render_for_every_slot():
    for s in cat.slots:
        card = texts.slot_card(s)
        assert s.name.split("'")[0] in card
        assert len(card) < 4000
    assert len(texts.about(cat)) < 4000
    assert len(texts.top_rtp(cat.top_rtp(10))) < 4000


def test_conflict_card_shows_range():
    card = texts.slot_card(cat.by_id["sweet-bonanza"])
    assert "range 96.48%" in card
