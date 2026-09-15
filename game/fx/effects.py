"""特效总线：规则层和画面之间的那层薄隔板。

Match 只负责喊"这里发生了一件事"（撞墙了、撞球了、有人在掉血），至于那件事长成
什么样完全由这里决定。好处是 Match 里不会出现一句绘制代码，特效也随时能整个换掉
——不想要震动了，把 camera.shake 去掉就行，规则一行不用动。

这一层是**单向**的：它只接收事实，从不回头去问游戏状态。所以它不会影响判定，
再怎么改都不会把对局改歪。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pygame.math import Vector2

from .camera import Camera
from ..config.settings import (
    COLOR_DOT_TEXT,
    COLOR_HEAL_TEXT,
    COLOR_IMPACT,
    DAMAGE_NUMBER_DRAG,
    DAMAGE_NUMBER_INTERVAL,
    DAMAGE_NUMBER_LIFETIME,
    DAMAGE_NUMBER_RISE,
    DAMAGE_NUMBER_SETTLE,
    RING_LIFETIME,
    RING_RADIUS_BASE,
    RING_RADIUS_MAX,
    RING_RADIUS_PER_SQRT_DAMAGE,
    RING_WIDTH,
    SHAKE_DAMAGE_REFERENCE,
    SHAKE_ON_BOUNCE,
    SHAKE_ON_IMPACT,
    WALL_RING_LIFETIME,
    WALL_RING_RADIUS,
    WALL_RING_SPEED_REFERENCE,
)
from .particle import ParticleSystem, RingParticle, TextParticle


@dataclass
class _DrainCounter:
    """持续伤害 / 回血的攒数器。

    吸血是每帧都在结算的，一帧报一个数字就是每秒 60 个，糊得什么都看不见。
    所以先攒着，攒够一个区间（span）再报一次；停了（idle）也补报一次，
    免得最后那点零头永远不显示。
    """

    color: tuple[int, int, int]
    prefix: str                       # "-" 掉血 / "+" 回血
    position: Vector2 = field(default_factory=Vector2)
    amount: float = 0.0     # 还没报出去的累计量
    span: float = 0.0       # 这批数字攒了多久
    idle: float = 0.0       # 距离上一次真的结算过了多久


def _brighten(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """把队色提亮一档。扣血数字要用自己的队色，但原色压在深色战场上太暗了。"""
    return tuple(min(255, channel + 90) for channel in color)


class Effects:
    """镜头抖动 + 粒子。Match 持有它，app 每帧把它画出来。"""

    def __init__(self, font=None) -> None:
        self.camera = Camera()
        self.particles = ParticleSystem(font)
        # 掉血和回血分成两张表。吸血是同时在两个人身上结算的：被吸的一方在掉，
        # 吸人的一方在回。合成一张表的话两边会攒进同一个计数器，数字就串了
        self._damage_over_time: dict[int, _DrainCounter] = {}
        self._healing: dict[int, _DrainCounter] = {}

    # ---------------- 规则层喊话的接口 ----------------
    def bounce(self, position: Vector2, color: tuple[int, int, int], speed: float) -> None:
        """球撞墙。position 是撞在墙上的那个点。"""
        scale = min(1.0, speed / WALL_RING_SPEED_REFERENCE)
        self._ring(position, color, WALL_RING_LIFETIME,
                   WALL_RING_RADIUS * (0.45 + 0.55 * scale))
        self.camera.shake(SHAKE_ON_BOUNCE * scale)

    def impact(self, first, second, first_takes: float, second_takes: float) -> None:
        """球撞球。first_takes 是 first 这一下掉了多少血，second_takes 同理。

        圆环画在两球中间（接触点），大小按两边伤害之和来——撞得越狠，圈炸得越大。
        """
        contact = (first.position + second.position) / 2
        total = first_takes + second_takes
        self._ring(contact, COLOR_IMPACT, RING_LIFETIME,
                   RING_RADIUS_BASE + math.sqrt(total) * RING_RADIUS_PER_SQRT_DAMAGE)
        self.camera.shake(
            SHAKE_ON_IMPACT * min(2.0, 0.35 + total / SHAKE_DAMAGE_REFERENCE)
        )
        if first_takes > 0:
            self._number(first.position, first_takes, _brighten(first.color))
        if second_takes > 0:
            self._number(second.position, second_takes, _brighten(second.color))

    def drain_damage(self, player: int, position: Vector2, amount: float) -> None:
        """持续伤害，也就是吸血里"被吸的那一头"。红字。

        颜色不跟队色走：红 = 正在被吸，和撞击的队色数字一眼就能分开。

        不震屏：吸血是每帧都在结算的，拿它抖屏幕会一直晃，那就没法看了。
        """
        counter = self._counter(self._damage_over_time, player, COLOR_DOT_TEXT, "-")
        counter.position.update(position)
        counter.amount += amount
        counter.idle = 0.0

    def heal(self, player: int, position: Vector2, amount: float) -> None:
        """回血，也就是吸血里"吸回来的那一头"。绿字。

        amount 要传**实际**回了多少（Ball.heal 的返回值），不是吸出来多少：
        满血的那一方再吸也是 0，飘个绿字就成了假数字。
        """
        counter = self._counter(self._healing, player, COLOR_HEAL_TEXT, "+")
        counter.position.update(position)
        counter.amount += amount
        counter.idle = 0.0

    @staticmethod
    def _counter(table: dict[int, _DrainCounter], player: int,
                 color: tuple[int, int, int], prefix: str) -> _DrainCounter:
        counter = table.get(player)
        if counter is None:
            counter = table[player] = _DrainCounter(color=color, prefix=prefix)
        return counter

    # ---------------- 推进 ----------------
    def update(self, dt: float) -> None:
        self.camera.update(dt)
        self.particles.update(dt)

        for table in (self._damage_over_time, self._healing):
            for counter in table.values():
                if counter.amount <= 0.0:
                    continue
                counter.span += dt
                counter.idle += dt
                if (counter.span < DAMAGE_NUMBER_INTERVAL
                        and counter.idle < DAMAGE_NUMBER_SETTLE):
                    continue
                self._number(counter.position, counter.amount,
                             counter.color, counter.prefix)
                counter.amount = 0.0
                counter.span = 0.0

    def draw(self, surface, offset: Vector2) -> None:
        self.particles.draw(surface, offset)

    def clear(self) -> None:
        """重开一局：抖到一半的残留和满屏粒子都不该带到下一局。"""
        self.camera.reset()
        self.particles.clear()
        self._damage_over_time.clear()
        self._healing.clear()

    # ---------------- 内部 ----------------
    def _ring(self, position: Vector2, color, lifetime: float, end_radius: float) -> None:
        self.particles.add(RingParticle(
            position=Vector2(position),
            lifetime=lifetime,
            max_lifetime=lifetime,
            color=color,
            start_radius=RING_RADIUS_BASE * 0.4,
            end_radius=min(end_radius, RING_RADIUS_MAX),
            width=RING_WIDTH,
        ))

    def _number(self, position: Vector2, amount: float, color,
                prefix: str = "-") -> None:
        # 初速按"总位移 = RISE"反推。drag 是每帧按比例衰减（指数衰减），
        # 这种衰减下总位移 = 初速 / drag，所以初速 = RISE × drag。
        # 减速度不变的话公式是另一套（少个系数），别照搬。
        velocity = Vector2(0.0, -DAMAGE_NUMBER_RISE * DAMAGE_NUMBER_DRAG)
        lifetime = DAMAGE_NUMBER_LIFETIME
        self.particles.add(TextParticle(
            position=Vector2(position),
            velocity=velocity,
            lifetime=lifetime,
            max_lifetime=lifetime,
            color=color,
            drag=DAMAGE_NUMBER_DRAG,
            text=f"{prefix}{amount:.0f}",
        ))
