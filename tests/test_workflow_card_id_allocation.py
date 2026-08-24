from types import SimpleNamespace

import pytest

from ui.workflow_parts.workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin


def _resolve(cards, requested_card_id=None):
    view = SimpleNamespace(cards=cards)
    return WorkflowViewCardLayoutMixin._resolve_card_id(view, requested_card_id)


def test_undoing_highest_added_card_reuses_its_id():
    cards = {card_id: object() for card_id in range(7)}

    added_id = _resolve(cards)
    assert added_id == 7
    cards[added_id] = object()

    del cards[added_id]

    assert _resolve(cards) == 7


def test_new_card_id_follows_current_highest_id():
    assert _resolve({0: object(), 3: object(), 8: object()}) == 9


def test_explicit_card_id_must_not_collide():
    with pytest.raises(ValueError, match="卡片 ID 已存在: 3"):
        _resolve({3: object()}, 3)
