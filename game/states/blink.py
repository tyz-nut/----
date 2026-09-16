"""幻影刺客那一下闪现突袭。

它和别的"挂在球上的状态"（刀、锤、钩锁）有一个根本区别：**它是技能生效中
的标记**。刀和锤是常驻的账本，球上挂着也说明不了什么；而 ball.blink 不为空
就等于"技能正在生效"，冷却要等它清掉才开始走（见 Ball.finish_skill）。

## 两段

1. **flash**——闪现的那一瞬。位置在开始那一刻就已经换好了，这一段纯粹是
   演出：屏幕边缘压暗 + 时间变慢。很短。
2. **slash**——持续挥砍。目标还在够得着的范围里就一直砍。

两段**同时开始、各自计时**，不是先后关系。所以闪完（flash 到 0）之后挥砍
还在继续，只是画面恢复正常速度——这正是要的效果：那一下"顿"只属于闪现。

## 为什么 flash 和 slash 是两个计时器而不是一个

因为衰减的东西不一样。暗角和时间倍速要的是**短促的一下**，挥砍要的是**一段
持续的输出**，把两者绑在一个倒计时上就只能二选一。而且减速期间游戏时间本身
走得慢，flash 用游戏时间计时意味着它会被自己拉长——这是要的（慢镜头本来就
该把那一下拉长），但那样一来它更不可能和挥砍共用一个长度了。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pygame.math import Vector2

if TYPE_CHECKING:
    # 只在类型检查时 import：ball.py 在运行时是 import 这个模块的（Ball 上挂着
    # blink 这一栏），真 import 进来就绕成一个圈了
    from ..core.ball import Ball


@dataclass
class BlinkStrike:
    """一次进行中的闪现突袭。"""

    target: Ball | None      # 砍的是哪一颗球。球是实体，直接存它本身（见 Ball 的 eq=False）
    facing: Vector2          # 挥砍朝向。**在闪现那一刻定死**，之后不跟着目标转
    slash_remaining: float   # 挥砍还剩几秒
    slash_total: float       # 这次挥砍一共几秒（画进度条用）
    flash_remaining: float   # 闪现那一下还剩几秒（暗角 + 减速跟着它走）
    flash_total: float
    slow_factor: float       # 闪现期间把游戏速度压到几倍
    damage_per_second: float # 挥砍每秒砍掉多少血
    reach: float             # 够得着多远才算砍到
    break_distance: float    # 拉开到这个距离就收招（见 Match.blink_broken）
    swing: float = 0.0       # 挥砍动画的相位，只是画的时候用

    @property
    def flashing(self) -> bool:
        return self.flash_remaining > 0.0

    @property
    def flash_ratio(self) -> float:
        """闪现那一下还剩几成，1 → 0。

        暗角直接拿它当强度，所以观感是"闪现的一瞬间边缘最黑，然后迅速退掉"。
        没有做渐入：闪现本身是瞬时的，暗角再慢慢淡入就成了"先黑了一下才闪"，
        顺序反了。
        """
        if self.flash_total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.flash_remaining / self.flash_total))

    @property
    def slash_progress(self) -> float:
        """挥砍走了几成，0 → 1。"""
        if self.slash_total <= 0.0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - self.slash_remaining / self.slash_total))
