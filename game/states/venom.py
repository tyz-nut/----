"""毒刺钉在墙上的刺，以及球身上叠着的中毒。

两样东西放在一个模块里，因为它们是一件事的两头：刺是**因**，中毒是**果**。
但它们的**归属**完全不同，这一点决定了两者写法的差别：

- Spike 钉在墙上，属于"我留下了什么"的账本（和 WebAnchor / Beam 同类），
  跟着放刺的那颗球走（见 Ball.spikes）。球死了账本也就没人看了。
- PoisonStack 是挂在**挨扎的那颗球**身上的减益（和 silence 同类），跟着中毒
  的人走（见 Ball.venom）。**它跟下毒的人再无关系**——毒进了身体就是自己的
  事了，下毒的那位中途死掉，毒照样走完。

## 刺为什么是永久的，却还要"蓄一会儿"

刺**不会消失**（用户定的，和激光、蛛丝一样不封顶），但扎过一次之后要等
spike_cooldown 秒才能再扎。没有这一步，对手贴着墙站在刺上就会每帧挨一下——
一秒六十次，比任何技能都狠。

所以真正决定"一根刺能叠出多少毒"的不是刺的数量，是刺的数量 **×** 对手在
刺旁边的停留时间 ÷ 蓄力间隔。这也正是"每层各走各的倒计时"（用户定的）会
有意思的地方：快速连扎叠出来的层数，比慢慢扎要高得多。
"""

from __future__ import annotations

from dataclasses import dataclass

from pygame.math import Vector2


@dataclass
class Spike:
    """墙上钉着的一根毒刺。

    数值（伤害、毒、蓄力间隔）在**插上去的那一刻**就烤在自己身上，和
    WebAnchor / Beam 一样：以后调技能参数不会把墙上已有的旧刺一起改掉。

    ready_in 是这个模块里唯一可变的东西，也是它和 WebAnchor（frozen）最大的
    区别——蛛丝钉上去就永远是那根丝，刺扎完一次要重新长出来。
    """

    point: Vector2          # 钉在墙面上的那一点
    side: str               # 哪一面墙（arena 的 LEFT/RIGHT/TOP/BOTTOM）。绘制用
    size: float             # 刺有多"大"。判定上等于给对方的半径加这么多
    damage: float           # 扎到那一下的一次性伤害
    poison_seconds: float   # 这一下叠上去的那层毒活多久
    poison_per_second: float  # 那一层每秒掉多少血
    cooldown: float         # 扎完一次要等多久才能再扎
    ready_in: float = 0.0   # 还差几秒重新长好。0 就是随时能扎

    def touches(self, center: Vector2, radius: float) -> bool:
        """这颗球有没有碰到这根刺。

        判定是"球心到刺那一点的**距离** ≤ 对方半径 + 刺的大小"，而不是
        "球心离墙面多近"：刺是从墙上伸出来的一小根，球沿着墙从它旁边擦过去
        **也算扎到**——这正是这个角色想要的，刺不是一堵墙，是一根钉在那儿的针。
        """
        reach = radius + self.size
        return (center - self.point).length_squared() <= reach * reach

    def tick(self, dt: float) -> None:
        """走一步蓄力。已经长好了就不动，免得负数越滚越大。"""
        if self.ready_in > 0.0:
            self.ready_in = max(0.0, self.ready_in - dt)

    @property
    def armed(self) -> bool:
        """长好了没有。没长好的刺不判定——它就挂在那儿当个记号。"""
        return self.ready_in <= 0.0

    def consume(self) -> None:
        """扎出去了：重新开始蓄力。"""
        self.ready_in = self.cooldown


@dataclass
class PoisonStack:
    """**一层**毒。每层各走各的倒计时（用户定的）。

    所以层数不是"一个数值 + 一个时长"，而是一把各自的沙漏：连扎三下就是三个
    错开的沙漏，最先扎的那个先漏完。这跟"共享倒计时、被扎就刷新时长"是两种
    完全不同的手感——那种是"离开刺之后还疼很久"，这种是"扎得越密越疼，一停
    就一层层褪掉"。

    damage_per_second 跟着层走，不在球上记一个总数：扎的时候是多少，这层就
    一直是那么多，中途改技能参数不会回头改已经中上的毒。
    """

    remaining: float
    damage_per_second: float

    def tick(self, dt: float) -> bool:
        """走一步，返回这一层是不是**该掉了**。

        用减而不是先判断：remaining 允许过冲到负数，调用方按返回值丢掉它就行，
        不必在这里夹一道 0——夹了反而要多一次比较。
        """
        self.remaining -= dt
        return self.remaining <= 0.0
