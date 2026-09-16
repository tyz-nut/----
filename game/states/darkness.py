"""黑夜降临的那一下黑屏。

和别的 state 都不一样：hook / blade / thrust / laser / web 都是"挂在某颗球身上
的东西"，而这个**不属于任何一颗球**——它盖的是整块战场，是一次全场事件。所以它
存在 Match 上（match.darkness），不是 ball.darkness。

它同时管两件事，而且是同一根时间轴上的两件事：

1. **什么时候换位**。黑屏不是为了好看，是为了把"双方位置和血量对调"这件事藏
   起来。所以对调发生在**黑到底的那一刻**（rise 走完），不是开始也不是结束
   —— 结束之后再换的话，玩家会眼睁睁看着两颗球瞬间挪窝。
2. **现在该黑到什么程度**。三段：渐暗（rise）、全黑（hold）、渐亮（fall）。
   换位就卡在渐暗和全黑之间那一瞬。

三段的比例是**观感**，放在 config/settings.py；整段多长是**节奏**，是技能的
duration。这里只负责按那两个数把 alpha 算出来。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 只在类型检查时 import：ball.py 在运行时走的是"球身上挂状态"这条路，
    # 真 import 进来就绕成一个圈了
    from ..core.ball import Ball


@dataclass
class Darkness:
    """一次正在降临的黑夜。"""

    rise: float          # 渐暗用几秒
    hold: float          # 全黑停几秒
    fall: float          # 渐亮用几秒
    caster: Ball | None = None   # 谁放的这一场。换位要不要发生是"从放的人的角度"看的
    slow_factor: float = 1.0   # 黑屏期间把游戏速度压到几倍（1 = 不压）
    elapsed: float = 0.0
    swapped: bool = False   # 这一下换过位没有（换位只在黑到底的那一刻做一次）

    @classmethod
    def for_duration(cls, total: float, caster: "Ball | None",
                     slow_factor: float = 1.0) -> "Darkness":
        """按整段时长切出三段。

        比例来自 config，加起来是 1，所以三段之和严格等于 total——技能的倒计时
        条和这里的黑屏是同一根时间轴，差一点就会看到"条走完了画面还黑着"。
        """
        from ..config.settings import (
            DARKNESS_FALL_RATIO,
            DARKNESS_HOLD_RATIO,
            DARKNESS_RISE_RATIO,
        )
        return cls(
            rise=total * DARKNESS_RISE_RATIO,
            hold=total * DARKNESS_HOLD_RATIO,
            fall=total * DARKNESS_FALL_RATIO,
            caster=caster,
            slow_factor=slow_factor,
        )

    @property
    def total(self) -> float:
        return self.rise + self.hold + self.fall

    @property
    def finished(self) -> bool:
        return self.elapsed >= self.total

    @property
    def blacked_out(self) -> bool:
        """黑到底了没有——换位就卡在这一刻。"""
        return self.elapsed >= self.rise

    @property
    def slowing(self) -> bool:
        """现在该不该压时间：**渐暗 + 全黑**压，渐亮时恢复。

        和换位卡在同一根时间轴上，但覆盖的区间不一样：换位只在渐暗走完的那
        一瞬发生一次，减速是渐暗一开始就压上、一直到全黑结束。所以黑夜的观感
        是"天慢慢黑下来的时候世界变慢了，天开始亮回来就恢复正常"，那个换位
        就发生在最慢、最黑的那一下里。

        注意它是**游戏时间**意义上的：减速期间 elapsed 走得也慢，所以渐暗 +
        全黑这一段在真实时间里会比设定的秒数长。这是要的效果——慢镜头本来就
        该把这段时间拉长。
        """
        return self.elapsed < self.rise + self.hold

    @property
    def alpha(self) -> float:
        """现在该黑到什么程度，0（全亮）~ 1（全黑）。"""
        if self.elapsed < self.rise:
            return self.elapsed / self.rise if self.rise > 0 else 1.0
        if self.elapsed < self.rise + self.hold:
            return 1.0
        remaining = self.total - self.elapsed
        return max(0.0, remaining / self.fall) if self.fall > 0 else 0.0
