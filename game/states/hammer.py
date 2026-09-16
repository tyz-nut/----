"""大锤那把绕着自己抡的锤子。

和 blade.py 是同一类（绕着自己转、每圈最多打一次），但**打中之后干什么**
完全是两回事，这也是这个文件唯一值得读的地方。

刀是"蹭一下扣一次血"，球该怎么飞还怎么飞。锤子是**打飞**：命中之后对方的
速度被整个重写。所以这里除了几何，还住着一小段物理。

## 物理模型

用户定的模型是：**对方撞上了一面正在移动的、无限质量的墙**。

"无限质量"是关键那一条——它让碰撞有确定解，而且解出来非常干净。一维碰撞里
质量 m 撞在质量 M 的墙上（墙速 u，球速 v）：

    v' = [(m - M)·v + 2M·u] / (m + M)
       → 令 M → ∞
       = 2u - v

（对方静止时是 v' = 2u，以墙速的两倍被弹出去；墙也静止时是 v' = -v，也就是
普通的弹墙。）M → ∞ 那一步是**逐分量**成立的，所以这个式子不用管法线方向、
也不用分解再合成，直接对速度矢量算就行——锤头从哪个角度砸上来都一样。

注意它**不守恒动量**：无限质量的东西本来就不参与动量守恒（能量还被凭空
注入）。这正是"打飞"要的效果——普通弹开的两球速度加起来不变，锤子这一下
是硬生生多给一份。所以别拿"两球碰撞"那套等质量公式来对照，两者不是一回事。

## 锤头有多快

u 是**锤头**的速度，不是大锤本人。锤头一边跟着球平移，一边绕着球转，所以

    u = 球的实际速度 + ω × 半径（切向）

转得越快、锤子越长、球飞得越快，u 就越大。因为伤害是相对速度的**平方**，
这三样都是双重收益——转得快不只是打得勤，还打得更疼。

切向那一项按叉乘展开成 (x, y) → (-y, x)：角度 θ 处的锤头位置是
中心 + r(cosθ, sinθ)，对时间求导就是上面那一条。

## 每圈一次

和刀一样：锤子压在敌人身上是**每帧**都挨着的，不记名单的话一秒就是 60 下。
转满一圈才清一次"这圈打过谁"。霸体目标打不飞、会一直待在锤子的道上，全靠
这一条兜着。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pygame.math import Vector2

TAU = math.tau


@dataclass
class Hammer:
    """绕着自己抡的一把锤子。

    形状是一个**锤头**加一根柄：柄从 inner_radius 伸到 outer_radius，锤头是
    外端那个半径为 head_radius 的圆。判定只认锤头不认柄——柄是握的地方，
    砸人的是头。所以贴着球边擦过去的敌人不算挨锤，锤头扫到才算。
    """

    angle: float = 0.0            # 当前抡到哪个角度（弧度）
    angular_speed: float = 0.0    # 角速度（弧度/秒）。带符号，抡的方向由它定
    inner_radius: float = 0.0     # 柄的内端离球心多远（贴着球面）
    outer_radius: float = 0.0     # 柄的外端，也就是锤头中心离球心多远
    head_radius: float = 0.0      # 锤头多大。判定用的是它，不是球半径
    damage_per_speed_sq: float = 0.0   # 伤害 = 相对速度² × 这个系数
    swept: float = 0.0            # 这一圈已经抡过的弧度
    struck: set[int] = field(default_factory=set)   # 这一圈已经砸过的球（存 Ball.uid）

    @property
    def direction(self) -> Vector2:
        return Vector2(math.cos(self.angle), math.sin(self.angle))

    def head_center(self, center: Vector2) -> Vector2:
        """锤头中心在世界坐标里的位置。"""
        return center + self.direction * self.outer_radius

    def shaft(self, center: Vector2) -> tuple[Vector2, Vector2]:
        """柄的两端（画它用）。"""
        direction = self.direction
        return (center + direction * self.inner_radius,
                center + direction * self.outer_radius)

    def head_velocity(self, carrier_velocity: Vector2) -> Vector2:
        """锤头此刻的速度 u = 球的实际速度 + 绕球的切向速度。

        取的是球**实际**在走的速度（含加速、含减速折扣），不是那份基础速度：
        锤子是长在球上的，球被推着走多快，锤头就跟着平移多快。
        """
        tangent = Vector2(-self.direction.y, self.direction.x)
        return carrier_velocity + tangent * (self.angular_speed * self.outer_radius)

    def impact(self, carrier_velocity: Vector2,
               target_velocity: Vector2) -> tuple[Vector2, float]:
        """这一锤砸中之后：(对方被砸成什么速度, 掉多少血)。

        速度按"撞上一面移动的无限质量墙"算（见文件开头）：

            u = 锤头速度，v = 对方速度 → v' = 2u - v

        伤害按**相对**速度的平方算，也就是 |u - v|² × damage_per_speed_sq。
        用相对速度而不是锤头速度，是因为迎面撞上来的敌人本来就该更疼：
        对方自己在往锤子上撞，那一下当然比站着不动重。
        """
        wall = self.head_velocity(carrier_velocity)
        relative = wall - target_velocity
        return (wall * 2.0 - target_velocity,
                relative.length_squared() * self.damage_per_speed_sq)

    def advance(self, dt: float) -> None:
        """抡一步。

        "抡过多少"用角速度的**绝对值**累加：转的方向可能反过来（负角速度），
        拿带符号的值累加会越转越负数，永远凑不满一圈，名单就再也清不掉了。
        """
        self.angle = (self.angle + self.angular_speed * dt) % TAU
        self.swept += abs(self.angular_speed) * dt
        if self.swept >= TAU:
            # 用减而不是清零：一帧转过的角度可能超过一圈（dt 被截断的畸形帧），
            # 清零会把多转的那部分吞掉，减掉才接着往下算
            self.swept -= TAU
            self.struck.clear()

    def hits(self, center: Vector2, point: Vector2, radius: float) -> bool:
        """锤头有没有碰到半径为 radius、圆心在 point 的球。

        只量锤头。柄不算——柄是握的地方，砸人的是头（见类文档）。
        """
        return self.head_center(center).distance_to(point) <= self.head_radius + radius

    def consume(self, uid: int) -> bool:
        """这一圈还没砸过这颗球就记上一笔。返回**该不该结算这一锤**。

        和刀那句是同一个道理：砸中了先问一句，问过的不加第二次，等 advance
        转满一圈把名单清空，才能再砸。打不飞的目标（霸体）会一直待在锤子的道
        上，全靠这一条兜着。

        记的是球的 uid 而不是玩家序号，理由和刀那边一样（见 Ball.uid）。
        """
        if uid in self.struck:
            return False
        self.struck.add(uid)
        return True
