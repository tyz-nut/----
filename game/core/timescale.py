"""游戏速度。

两样东西乘在一起：

- **base**：玩家自己拧的那个滑块（左栏），0.25x ~ 3x。
- **技能压的系数**：谁想让时间慢下来，谁就在这一帧申报一个因子。

    最终倍速 = base × 所有因子

（叠加方式定的就是"相乘"。代价是滑块 0.25x 再碰上技能 0.25x 就是 0.0625x，
基本定住——极值不用管，这是刻意的选择。）

## 为什么是"每帧申报"而不是"推一个带时长的减速进去"

时长的口径会打架。减速期间游戏时间本身是慢的，那么"这个减速持续 0.3 秒"
到底是 0.3 秒真实时间还是 0.3 秒游戏时间？取前者就得和真实时钟对表（还要
处理暂停），取后者它会自己把自己拉长。

申报式没有这个问题——"我现在还在不在减速"本来就是技能状态的一部分（刺客
在不在闪现、黑夜走没走过全黑那一段），技能自己最清楚，让它每帧答一句就行。
代价只有一个：忘了申报就等于解除了，所以每帧开头要先把上一帧的申报清空。

这和 Ball.speed_scale 是同一个套路（每帧重置、谁要谁申报），只是作用范围
从一颗球变成整局。

## 谁在用

- 左栏滑块：直接写 base
- 幻影刺客的闪现：闪的那一下压一个因子
- 死灵法师的黑夜：渐暗到全黑那一段压一个因子

以后再有"放慢时间"的技能，在 Match.begin_frame 里加一句申报即可。
"""

from __future__ import annotations

from ..config.settings import (
    TIME_SCALE_MAX,
    TIME_SCALE_MIN,
)


class TimeScale:
    """这一局的时间倍速。Match 持有它，每帧开头重收一次申报。"""

    def __init__(self, base: float = 1.0) -> None:
        self._base = _clamp(base)
        self._factors: dict[str, float] = {}

    @property
    def base(self) -> float:
        """滑块那一档，已经夹在 TIME_SCALE_MIN ~ MAX 之间。"""
        return self._base

    @base.setter
    def base(self, value: float) -> None:
        self._base = _clamp(value)

    @property
    def factors(self) -> dict[str, float]:
        """本帧申报上来的因子（快照，改它不影响这里）。"""
        return dict(self._factors)

    def push(self, key: str, factor: float) -> None:
        """申报一个速度因子。

        同一个 key 每帧重复申报就是覆盖，不会累加——这正是"每帧答一句"要的
        效果。key 用来区分来源，所以不同来源之间天然不会互相踩。
        """
        self._factors[key] = factor

    def reset(self) -> None:
        """清空本帧的申报。每帧开头调，之后由各个来源重新申报。"""
        self._factors.clear()

    @property
    def scale(self) -> float:
        """这一帧真正用的倍速。"""
        result = self._base
        for factor in self._factors.values():
            result *= factor
        return result

    @property
    def slowed(self) -> bool:
        """现在是不是有技能在压时间（滑块开着 3x 也算，那个是玩家自己拧的）。"""
        return bool(self._factors)


def _clamp(value: float) -> float:
    return min(TIME_SCALE_MAX, max(TIME_SCALE_MIN, value))
