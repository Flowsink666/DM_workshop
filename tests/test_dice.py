import random

import pytest

from dm_workshop.dice import roll
from dm_workshop.errors import RuleError


def test_critical_doubles_dice_not_modifier():
    result = roll("1d6+3", rng=random.Random(5), critical=True)
    assert result.groups[0].count == 2
    assert result.total == sum(result.groups[0].rolls) + 3


@pytest.mark.parametrize("expression", ["", "1d1", "0d6", "2d6++3", "abc"])
def test_invalid_expressions(expression):
    with pytest.raises(RuleError):
        roll(expression)


def test_mixed_expression_is_auditable():
    result = roll("2d6+1d4-2", rng=random.Random(42))
    assert len(result.groups) == 2
    assert result.modifier == -2
    assert result.total == sum(sum(g.rolls) for g in result.groups) - 2

