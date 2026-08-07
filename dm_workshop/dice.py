"""可注入随机源、可审计的骰子表达式。"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

from dm_workshop.errors import RuleError

_TERM = re.compile(r"([+-]?)(?:(\d*)d(\d+)|(\d+))", re.IGNORECASE)


@dataclass(frozen=True)
class DieGroup:
    """同一组骰子的面数、结果和正负号。"""
    count: int
    sides: int
    rolls: list[int]
    sign: int = 1


@dataclass(frozen=True)
class RollResult:
    """完整骰点结果；保留每颗骰子，便于 AI 和操作日志复核。"""
    expression: str
    groups: list[DieGroup]
    modifier: int
    total: int
    critical: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def roll(expression: str, *, rng: random.Random | None = None,
         critical: bool = False) -> RollResult:
    """投掷 NdS 与整数修正组成的表达式。

    重击只翻倍伤害骰数量，不翻倍固定修正值。
    """
    compact = expression.replace(" ", "")
    if not compact:
        raise RuleError("骰子表达式不能为空")
    rng = rng or random.SystemRandom()
    pos = 0
    groups: list[DieGroup] = []
    modifier = 0
    # 按位置连续匹配，任何无法消费的字符都会使整个表达式失败。
    for match in _TERM.finditer(compact):
        if match.start() != pos:
            raise RuleError(f"无效骰子表达式: {expression!r}")
        sign = -1 if match.group(1) == "-" else 1
        if match.group(3):
            count = int(match.group(2) or "1")
            sides = int(match.group(3))
            if not 1 <= count <= 100 or not 2 <= sides <= 1000:
                raise RuleError(f"骰子参数超出范围: {match.group(0)!r}")
            actual_count = count * (2 if critical else 1)
            values = [rng.randint(1, sides) for _ in range(actual_count)]
            groups.append(DieGroup(actual_count, sides, values, sign))
        else:
            modifier += sign * int(match.group(4))
        pos = match.end()
    if pos != len(compact):
        raise RuleError(f"无效骰子表达式: {expression!r}")
    total = modifier + sum(g.sign * sum(g.rolls) for g in groups)
    return RollResult(expression, groups, modifier, total, critical)


def roll_d20(*, rng: random.Random | None = None,
             advantage: bool | None = None) -> dict:
    rng = rng or random.SystemRandom()
    rolls = [rng.randint(1, 20)] if advantage is None else [
        rng.randint(1, 20), rng.randint(1, 20)
    ]
    kept = rolls[0] if advantage is None else (
        max(rolls) if advantage else min(rolls)
    )
    return {"rolls": rolls, "kept": kept, "advantage": advantage}
