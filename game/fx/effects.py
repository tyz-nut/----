"""特效总线：规则层和画面之间的那层薄隔板。

Match 只负责喊"这里发生了一件事"（撞墙了、撞球了、有人在掉血），至于那件事长成
什么样完全由这里决定。好处是 Match 里不会出现一句绘制代码，特效也随时能整个换掉
——不想要震动了，把 camera.shake 去掉就行，规则一行不用动。

这一层是**单向**的：它只接收事实，从不回头去问游戏状态。所以它不会影响判定，
再怎么改都不会把对局改歪。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pygame.math import Vector2

from .camera import Camera
from ..config.settings import (
    COLOR_DOT_TEXT,
    COLOR_HEAL_TEXT,
    DAMAGE_NUMBER_INTERVAL,
    DAMAGE_NUMBER_SETTLE,
    SHAKE_ON_BOUNCE,
    WALL_RING_LIFETIME,
    WALL_RING_RADIUS,
    WALL_RING_SPEED_REFERENCE,
)
from .impact import HitFX
from .particle import ParticleSystem, add_number, add_ring


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


class Effects:
    """镜头抖动 + 粒子。Match 持有它，app 每帧把它画出来。"""

    def __init__(self, font=None) -> None:
        self.camera = Camera()
        self.particles = ParticleSystem(font)
        # 命中（撞上、刀、锤、穿刺）的画面反应单独封成一块，见 fx/impact.py。
        # 持续伤害不从这里走——它只飘红字，理由是"逐帧震屏等于全程在晃"
        self.hits = HitFX(self.particles, self.camera)
        # 屏幕边缘压暗的强度，0~1。和粒子、抖动不同，这是**状态**不是事件：
        # 所以它走"每帧重新申报"，不攒在粒子系统里（见 Match.begin_frame）
        self.vignette = 0.0
        # 掉血和回血分成两张表。吸血是同时在两个人身上结算的：被吸的一方在掉，
        # 吸人的一方在回。合成一张表的话两边会攒进同一个计数器，数字就串了
        self._damage_over_time: dict[int, _DrainCounter] = {}
        self._healing: dict[int, _DrainCounter] = {}

    # ---------------- 规则层喊话的接口 ----------------
    def bounce(self, position: Vector2, color: tuple[int, int, int], speed: float) -> None:
        """球撞墙。position 是撞在墙上的那个点。

        撞墙**不算命中**，所以它不走 impact 那一套：没有伤害、也没有顿帧，
        就一个圈加一点点抖。它只是"撞到了墙"，不是"挨了一下"。
        """
        scale = min(1.0, speed / WALL_RING_SPEED_REFERENCE)
        add_ring(self.particles, position, color, WALL_RING_LIFETIME,
                 WALL_RING_RADIUS * (0.45 + 0.55 * scale))
        self.camera.shake(SHAKE_ON_BOUNCE * scale)

    def drain_damage(self, player: int, position: Vector2, amount: float) -> None:
        """持续伤害，也就是吸血里"被吸的那一头"。红字。

        颜色不跟队色走：红 = 正在被吸，和撞击的队色数字一眼就能分开。

        **只飘字，不震屏**：吸血、激光、蛛丝这些是每帧都在结算的，逐帧加震动
        等于全程一直晃。所以这个游戏里"震"等于"挨了一下"，不是"在掉血"。
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

    def set_vignette(self, strength: float) -> None:
        """屏幕边缘压暗到多黑，0~1。谁要压谁申报（规则层每帧重新申报一次）。

        多个来源同时要压时取**最深的那个**，不是相加：相加会在两个技能撞在
        一起时直接压成全黑，而"更黑"本来也没有意义——强度到 1 就到头了。
        """
        self.vignette = max(self.vignette, min(1.0, strength))

    def reset_screen(self) -> None:
        """清掉上一帧申报的画面状态。每帧开头调，之后由各个来源重新申报。"""
        self.vignette = 0.0

    # ---------------- 推进 ----------------
    def update(self, dt: float, real_dt: float | None = None) -> None:
        """dt 是**游戏时间**（已经被时间倍速缩过），粒子和镜头都走它。

        real_dt 是真实流逝的时间，**只有顿帧走它**。理由见 fx/impact.py 里
        HitFX.hit_stop 的说明：顿帧自己在压时间，用游戏时间计时会被自己拉长。
        不传就当成没减速（两者相同）。
        """
        self.camera.update(dt)
        self.particles.update(dt)
        self.hits.update(dt if real_dt is None else real_dt)

        for table in (self._damage_over_time, self._healing):
            for counter in table.values():
                if counter.amount <= 0.0:
                    continue
                counter.span += dt
                counter.idle += dt
                if (counter.span < DAMAGE_NUMBER_INTERVAL
                        and counter.idle < DAMAGE_NUMBER_SETTLE):
                    continue
                add_number(self.particles, counter.position, counter.amount,
                           counter.color, counter.prefix)
                counter.amount = 0.0
                counter.span = 0.0

    def draw(self, surface, offset: Vector2) -> None:
        self.particles.draw(surface, offset)

    def clear(self) -> None:
        """重开一局：抖到一半的残留和满屏粒子都不该带到下一局。"""
        self.camera.reset()
        self.particles.clear()
        self.hits.reset()
        self.reset_screen()
        self._damage_over_time.clear()
        self._healing.clear()
