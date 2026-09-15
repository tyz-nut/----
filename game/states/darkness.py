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


@dataclass
class Darkness:
    """一次正在降临的黑夜。"""

    rise: float          # 渐暗用几秒
    hold: float          # 全黑停几秒
    fall: float          # 渐亮用几秒
    caster: int = 0      # 谁放的这一场。换位要不要发生是"从放的人的角度"看的
    elapsed: float = 0.0
    swapped: bool = False   # 这一下换过位没有（换位只在黑到底的那一刻做一次）

    @classmethod
    def for_duration(cls, total: float, caster: int) -> "Darkness":
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
    def alpha(self) -> float:
        """现在该黑到什么程度，0（全亮）~ 1（全黑）。"""
        if self.elapsed < self.rise:
            return self.elapsed / self.rise if self.rise > 0 else 1.0
        if self.elapsed < self.rise + self.hold:
            return 1.0
        remaining = self.total - self.elapsed
        return max(0.0, remaining / self.fall) if self.fall > 0 else 0.0
