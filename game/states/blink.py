"""幻影刺客那一套闪现突袭。

它和别的"挂在球上的状态"（刀、锤、钩锁）有一个根本区别：**它是技能生效中
的标记**。刀和锤是常驻的账本，球上挂着也说明不了什么；而 ball.blink 不为空
就等于"技能正在生效"，冷却要等它清掉才开始走（见 Ball.finish_skill）。

## 一套连招，不是一段挥砍

闪现、砍一刀、闪到别处、再砍一刀……一直重复到时间走完。所以它不是"贴上去了
就一直砍"，而是**一刀一个落点**：每一刀之前先换一个位置。

起手那一下有讲究：**闪到敌人身后**（对面运动方向的反面），之后的每一刀则是
**围着敌人随机挑一个方向**。起手是"咬尾巴"——那是"我盯上你了"这个决定，得
看得出来是从背后扑上去的；后面就是纯粹的乱刀，落点随机，读不出来下一刀从哪
来（用户定的）。

## 砍的时候速度为 0

挥砍期间刺客**定在原地不动**（每一帧把速度摁回 0），落点全靠闪现换。这不是
"站着挨打"的设定漏洞，是这个技能的代价：它换成了一整套必定命中的乱刀——
落点是自己挑的，对方躲不掉，那就得拿"这几个时刻我动不了"来付账。

**被击退是唯一的例外**：期间要是被外力推走了（撞上别人、被锤子砸飞），那份
速度会被记下来（见 Match.update_blinks），收招的时候按它走，而不是按"往敌人
反方向离开"那条常规。挨了一锤还按原计划飘走就太假了。

## 为什么 flash 和 slash 是两个计时器而不是一个

因为衰减的东西不一样。暗角和时间倍速要的是**短促的一下**，整套连招要的是
**一段持续的输出**，把两者绑在一个倒计时上就只能二选一。而且减速期间游戏
时间本身走得慢，flash 用游戏时间计时意味着它会被自己拉长——这是要的（慢镜头
本来就该把那一下拉长），但那样一来它更不可能和连招共用一个长度了。

每一次闪现都会**重新压一次**暗角，所以一套连招看下来是"闪一下、闪一下、
闪一下"，而不是只有起手黑一次。
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
    """一次进行中的闪现突袭（一整套连招）。"""

    target: Ball | None      # 砍的是哪一颗球。球是实体，直接存它本身（见 Ball 的 eq=False）
    facing: Vector2          # 挥砍朝向。**每次闪现那一刻定死**，两次闪现之间不跟着目标转
    slash_remaining: float   # 这一整套还剩几秒
    slash_total: float       # 一共几秒（画进度条用）
    flash_remaining: float   # 这一次闪现还剩几秒（暗角 + 减速跟着它走）
    flash_total: float
    slow_factor: float       # 闪现期间把游戏速度压到几倍
    slash_damage: float      # 砍一刀掉多少血。**一刀一结算**，不是每秒
    blink_distance: float    # 每一次闪，落在离敌人多远的地方
    blink_interval: float    # 隔多久闪一下、砍一刀
    next_blink: float        # 离下一刀还有几秒
    exit_speed: float        # 正常收招之后，朝敌人反方向离开的速度
    reach: float             # 挥砍弧光画多大。判定不用它（落点是刺客自己挑的，
                             # 每次都在这个半径以内，见 match.blink_to_side）
    # 期间被外力推走的那份速度。None = 没被打飞过，收招走常规那条。
    # 见 update_blinks 里怎么认出来的
    knockback: Vector2 | None = None
    slashes: int = 0         # 已经砍了几刀（起手那一刀算第一刀）
    swing: float = 0.0       # 挥砍动画的相位，只是画的时候用

    @property
    def flashing(self) -> bool:
        return self.flash_remaining > 0.0

    @property
    def flash_ratio(self) -> float:
        """这一次闪现还剩几成，1 → 0。

        暗角直接拿它当强度，所以观感是"闪现的一瞬间边缘最黑，然后迅速退掉"。
        没有做渐入：闪现本身是瞬时的，暗角再慢慢淡入就成了"先黑了一下才闪"，
        顺序反了。
        """
        if self.flash_total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.flash_remaining / self.flash_total))

    @property
    def slash_progress(self) -> float:
        """整套连招走了几成，0 → 1。"""
        if self.slash_total <= 0.0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - self.slash_remaining / self.slash_total))
