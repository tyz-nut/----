"""激光留下的那些线和点。

和 hook.py 是一对：那个是"技能甩出去的一个飞行物"，这个是"技能在墙上留下的
痕迹"。共同点是两者都**不保存技能状态**——它们只描述场上的形状，什么时候
该结算、结算多少由 Match 说了算。

激光和钩锁有一处关键的不同：钩锁挂在球上、球一死就没了，而激光是**画在墙上
的**，画完就留在那儿。所以这里的容器叫 LaserField（场地布局），挂在球上只是
为了知道"这是谁画的"，以及重开时好清掉。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pygame.math import Vector2

# 四面墙的名字。用字符串而不是 Enum：它只用来比相等（"这次撞的和攒着的是不是
# 同一面"），没有别处要遍历或排序，Enum 的仪式感在这里换不来什么
LEFT = "left"
RIGHT = "right"
TOP = "top"
BOTTOM = "bottom"


def distance_to_segment(point: Vector2, start: Vector2, end: Vector2) -> float:
    """点到线段的最短距离。

    注意是**线段**不是直线：激光只画在墙上那两个点之间，越过端点的部分不算，
    否则球贴着墙根走也会被"延长出去的激光"打到。
    """
    segment = end - start
    length_squared = segment.length_squared()
    if length_squared <= 1e-12:
        return (point - start).length()
    # 把点投影到线段所在直线上，再夹到 [0, 1]——夹这一下就是"线段"和"直线"的区别
    t = max(0.0, min(1.0, (point - start).dot(segment) / length_squared))
    return (point - (start + segment * t)).length()


@dataclass
class Beam:
    """一条激光：两端都钉在墙面上，永久留在场上。

    damage_per_second 记在**线上**而不是让它回头去问技能：技能是每次撞墙时
    现取的参数，记在线上之后，一条线从生到死带着的就是它出生那一刻的数值，
    以后调技能参数也不会把场上的旧线一起改掉。
    """

    start: Vector2
    end: Vector2
    damage_per_second: float

    def hits(self, point: Vector2, radius: float) -> bool:
        """这条线有没有碰到一个半径为 radius、圆心在 point 的球。"""
        return distance_to_segment(point, self.start, self.end) <= radius


@dataclass
class LaserField:
    """一个激光角色在场上的布局：一个攒着待连的点 + 已经连出来的那些线。

    两种模式（见 Ball.record_wall_hit）：

    - 普通模式：pending 是 None，什么也不连
    - 连线模式：pending 攒着一个墙面上的点，等下一次撞**另一面**墙

    没有倒计时、没有上限：撞出来的线一直留着。这是刻意的——激光的输出方式就是
    "把战场一点点切碎"，会过期的话就成了一次性的了。代价是打久了场上线很多，
    所以画的时候要压暗一些（见 config.COLOR_BEAM 的说明）。
    """

    pending: Vector2 | None = None     # 连线模式里攒着的那个点（在墙面上）
    pending_side: str = ""             # 它在哪面墙上
    beams: list[Beam] = field(default_factory=list)

    @property
    def armed(self) -> bool:
        """是不是正处在连线模式（攒着一个点等连）。"""
        return self.pending is not None
