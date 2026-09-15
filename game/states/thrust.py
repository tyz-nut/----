"""武士那次穿刺剩下的那点事。

穿刺是一个**有时长的位移**：出手之后球不再按自己的动量走，而是沿着一条
锁死的方向，用极快的速度冲一段距离。这段时间里它既不是"按动量飞"
（那要走 ball.update），也不是"被定住"（那是 frozen）——所以和钩锁一样，
需要在球上挂一个状态，让 Match 知道"这颗球这几帧归别人管"。

方向是**出手那一刻**就锁死的，往后敌人怎么动都不会再改：这正是"能躲开"的
来源。出手时朝着敌人，之后各走各的——敌人跑得快，冲过去的时候它已经不在
那条线上了。

撞墙就停：冲的距离要跟"到墙还有多远"比一下，取小的那个。所以不会穿墙，
也不会贴着墙出手时冲出去。
"""

from __future__ import annotations

from dataclasses import dataclass

from pygame.math import Vector2


@dataclass
class Thrust:
    """一次还没冲完的穿刺。"""

    direction: Vector2      # 锁死的冲刺方向（单位向量）
    remaining: float        # 沿着这个方向还剩多少像素没冲
    speed: float            # 冲刺速度（像素/秒），远高于正常移速
    damage: float           # 冲到了扣这么多
    exit_speed: float       # 冲完接着按这个速度走（出手那一刻的正常速度）
    landed: bool = False    # 这一下已经打出去了（一次穿刺只打一下）

    @property
    def finished(self) -> bool:
        return self.remaining <= 1e-9
