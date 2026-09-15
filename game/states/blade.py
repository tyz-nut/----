"""武士那把绕着自己转的刀。

和 laser.py / hook.py 同一类：技能留在球上的**形状**，几何和推进写在这里，
谁挨打、挨多少由 Match 去问。

刀和激光的区别在于"什么时候算蹭到"。激光是一条钉死不动的线段，每帧量一下
距离就行；刀在转，如果也这么干，刀压在敌人身上时**每一帧都会蹭一下**——
每秒 60 下，一秒钟要人命。所以刀还得多记一件事：这一圈已经蹭过谁。
转满一圈才把这个名单清空，"每圈蹭一次"就落在这一句上。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pygame.math import Vector2

from ..core.segment import distance_to_segment

TAU = math.tau


@dataclass
class Blade:
    """绕着自己转的一把刀。

    刀是一个**线段**（inner_radius 到 outer_radius，沿当前角度），不是一个点。
    做成一截线段是为了"刀刃"这个形状：贴着球边一小段在扫，比一个点在绕圈
    看起来像回事，判定范围也更符合直觉。
    """

    angle: float = 0.0            # 当前转到哪个角度（弧度）
    angular_speed: float = 0.0    # 角速度（弧度/秒）。带符号，转的方向由它定
    inner_radius: float = 0.0     # 刀刃内端离球心多远
    outer_radius: float = 0.0     # 刀刃外端
    damage: float = 0.0           # 蹭一下扣多少血
    swept: float = 0.0            # 这一圈已经转过的弧度
    struck: set[int] = field(default_factory=set)   # 这一圈已经蹭过谁

    @property
    def direction(self) -> Vector2:
        return Vector2(math.cos(self.angle), math.sin(self.angle))

    def reach(self, center: Vector2) -> tuple[Vector2, Vector2]:
        """刀刃的两端在世界坐标里的位置（画它、判定它都用这个）。"""
        direction = self.direction
        return (center + direction * self.inner_radius,
                center + direction * self.outer_radius)

    def advance(self, dt: float) -> None:
        """转一步。

        "转过多少"用角速度的**绝对值**累加，因为转的方向可能反过来（负角速度），
        拿带符号的值累加会越转越负数，永远凑不满一圈，那个名单就再也清不掉了。
        """
        self.angle = (self.angle + self.angular_speed * dt) % TAU
        self.swept += abs(self.angular_speed) * dt
        if self.swept >= TAU:
            # 用减而不是清零：一帧转过的角度可能超过一圈（dt 被截断的畸形帧），
            # 清零会把多转的那部分吞掉，减掉才接着往下算
            self.swept -= TAU
            self.struck.clear()

    def tip_velocity(self, carrier_velocity: Vector2) -> Vector2:
        """刀尖此刻的速度 = 球的实际速度 + 绕球的切向速度。

        和 Hammer.head_velocity 是同一个式子，用途也一样：命中特效要按"这一下
        撞得多快"决定抖多重，而刀尖才是撞上去的那个东西——站着不动的武士，
        转着的刀一样削人，光看武士自己的速度会把这一下算成 0。

        切向那一项按叉乘展开成 (x, y) → (-y, x)。
        """
        tangent = Vector2(-self.direction.y, self.direction.x)
        return carrier_velocity + tangent * (self.angular_speed * self.outer_radius)

    def hits(self, center: Vector2, point: Vector2, radius: float) -> bool:
        """刀刃有没有碰到半径为 radius、圆心在 point 的球。"""
        start, end = self.reach(center)
        return distance_to_segment(point, start, end) <= radius

    def consume(self, player: int) -> bool:
        """这一圈还没蹭过这个玩家就记上一笔。返回**该不该结算伤害**。

        这就是"每圈一次"的全部实现：蹭到了先问一句，问过的人不加第二次，
        等 Blade.advance 转满一圈把名单清空，才能再蹭。
        """
        if player in self.struck:
            return False
        self.struck.add(player)
        return True
