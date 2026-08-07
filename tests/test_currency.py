import pytest

from dm_workshop.currency import coins_to_cp, cp_to_coins
from dm_workshop.errors import RuleError


def test_exact_coin_conversion():
    assert coins_to_cp(pp=1, gp=2, ep=3, sp=4, cp=5) == 1395
    assert cp_to_coins(1395) == {
        "pp": 1, "gp": 3, "sp": 9, "cp": 5, "total_cp": 1395,
    }


def test_negative_coins_rejected():
    with pytest.raises(RuleError):
        coins_to_cp(gp=-1)
