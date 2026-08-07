"""D&D 5e 货币精确换算；持久化时统一使用铜币作为最小单位。"""

from dm_workshop.errors import RuleError

RATES = {"pp": 1000, "gp": 100, "ep": 50, "sp": 10, "cp": 1}


def coins_to_cp(*, pp: int = 0, gp: int = 0, ep: int = 0,
                sp: int = 0, cp: int = 0) -> int:
    values = {"pp": pp, "gp": gp, "ep": ep, "sp": sp, "cp": cp}
    if any(int(value) < 0 for value in values.values()):
        raise RuleError("货币数量不能为负")
    return sum(int(values[key]) * rate for key, rate in RATES.items())


def cp_to_coins(total_cp: int) -> dict[str, int]:
    if int(total_cp) < 0:
        raise RuleError("铜币总值不能为负")
    remaining = int(total_cp)
    result: dict[str, int] = {}
    # 规范展示不主动产生琥珀金币，但输入时仍接受 EP 并精确折算。
    for key in ("pp", "gp", "sp", "cp"):
        result[key], remaining = divmod(remaining, RATES[key])
    result["total_cp"] = int(total_cp)
    return result
