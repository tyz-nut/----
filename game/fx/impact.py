"""一次"命中了"的画面反应总成。

规则层（Match）只知道"谁打了谁、在哪、掉了多少血、撞得多快、有没有把人打飞"，
至于这一下该炸几个圈、抖多重、飘什么数字、要不要顿帧——全在这个文件里。

单独封成一块的理由有两个：

1. **碰撞不是只有震动**。它还有圆圈的粒子特效、扣血数字、顿帧，以后还要加音效。
   这几样必须一起改、一起调，散在 Effects 里迟早会漏掉一处。
2. **加音效要有一个口子**。所有命中都从 HitFX.strike 走，加声音就是在那一处补
   一行，不用回头满仓库找"哪里算命中"。

## 什么算"命中"

只有**一次性**的打击走这里：两个角色撞上、绕身刀蹭到、巨锤砸中、穿刺捅中。
持续伤害（吸血、激光、蛛丝、钩锁拖拽、幻影的挥砍）**不走这里**——它们是每帧都
在结算的，逐帧震屏等于全程一直晃，那不是"被打到了"，那是屏幕坏了。持续伤害只
飘红字（见 Effects.drain_damage）。

所以这个游戏里"震"的含义是**挨了一下**，不是"在掉血"。

## 震动有多大

一个通用公式（HitFX.shake_amount），三样加起来：

    基础（撞击一条、技能命中一条）
      × 伤害项（这一下掉了多少血）
      × 速度项（撞得多快）
      + 额外（撞上、打飞）

系数全在 config/settings.py。乘除关系是刻意的：伤害和速度都是"越狠越强"的
**倍率**，而"撞上"和"打飞"是几种事件里各自独有的那一下**加量**。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pygame.math import Vector2

from ..config.settings import (
    COLOR_IMPACT,
    HITSTOP_SECONDS,
    RING_LIFETIME,
    RING_RADIUS_BASE,
    RING_RADIUS_PER_SQRT_DAMAGE,
    SHAKE_DAMAGE_REFERENCE,
    SHAKE_EXTRA_COLLISION,
    SHAKE_EXTRA_KNOCKBACK,
    SHAKE_KNOCKBACK_REFERENCE,
    SHAKE_ON_HIT,
    SHAKE_ON_IMPACT,
    SHAKE_SPEED_REFERENCE,
    SHAKE_SPEED_SHARE,
)
from .particle import ParticleSystem, add_number, add_ring

if TYPE_CHECKING:
    from ..core.ball import Ball


def brighten(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """把队色提亮一档。扣血数字要用自己的队色，但原色压在深色战场上太暗了。"""
    return tuple(min(255, channel + 90) for channel in color)


@dataclass(frozen=True)
class Damage:
    """一次命中里，某颗球掉了多少血。

    位置和颜色跟着**挨打的那颗球**走，不跟着命中点走：撞在两球中间的那一下，
    两个数字该从各自的球上飘起来，不然会叠在一起。
    """

    player: int
    position: Vector2
    amount: float
    color: tuple[int, int, int]

    @classmethod
    def of(cls, ball: Ball, amount: float) -> "Damage":
        return cls(
            player=ball.player,
            position=Vector2(ball.position),
            amount=amount,
            color=brighten(ball.color),
        )


@dataclass(frozen=True)
class Hit:
    """一次命中的全部事实。

    规则层只负责把这个凑出来，怎么反应由 HitFX 决定。两个造法分别对应两大类，
    用哪个一眼能看出来这一下是什么性质：

    - Hit.between 两个角色直接撞上
    - Hit.on      技能命中（刀、锤、穿刺）

    speed 是"这一下撞得多快"，各家取各家有意义的那份：撞击取两球的**相对速度**，
    巨锤取锤头速度（它才是砸上去的那个东西），穿刺取冲刺速度，刀取刀尖速度。
    硬凑成同一个口径反而会说谎——站着不动的武士，转着的刀一样削人。
    """

    position: Vector2
    speed: float = 0.0
    damages: tuple[Damage, ...] = ()
    collision: bool = False      # 是不是两个角色直接撞上（额外震动 + 顿帧）
    knockback: float = 0.0       # 被打飞的速度变化量，没打飞就是 0
    color: tuple[int, int, int] = COLOR_IMPACT

    @classmethod
    def between(cls, first: Ball, second: Ball, first_takes: float = 0.0,
                second_takes: float = 0.0, speed: float = 0.0) -> "Hit":
        """两个角色撞上：圆环炸在接触点（两球中间），两边各飘各的数字。"""
        damages = []
        if first_takes > 0.0:
            damages.append(Damage.of(first, first_takes))
        if second_takes > 0.0:
            damages.append(Damage.of(second, second_takes))
        return cls(
            position=(first.position + second.position) / 2,
            speed=speed,
            damages=tuple(damages),
            collision=True,
        )

    @classmethod
    def on(cls, attacker: Ball, victim: Ball, damage: float,
           speed: float = 0.0, knockback: float = 0.0) -> "Hit":
        """技能命中：只有挨打的那一方飘数字，打人的一方不掉血。"""
        damages = (Damage.of(victim, damage),) if damage > 0.0 else ()
        return cls(
            position=(attacker.position + victim.position) / 2,
            speed=speed,
            damages=damages,
            knockback=knockback,
        )

    @property
    def total_damage(self) -> float:
        return sum(damage.amount for damage in self.damages)


class HitFX:
    """命中的画面反应：圆环 + 震动 + 扣血数字 + 顿帧（以后的音效）。

    它不持有 Match，也不回头看游戏状态——只认传进来的这个 Hit。
    """

    def __init__(self, particles: ParticleSystem, camera) -> None:
        self._particles = particles
        self._camera = camera
        # 顿帧还剩几秒。**按真实时间倒计时**，是全场唯一一个不按游戏时间的时长。
        #
        # 别的时长（技能持续、冷却、闪现的暗角）都走游戏时间，这里不能跟着走：
        # 顿帧自己就在压时间，用被自己压过的时间计时，它会被自己拉长 1/HITSTOP_FACTOR
        # 倍——0.06 秒的顿帧会变成 0.24 秒，那就不叫"非常短"了。
        self.hit_stop = 0.0

    @property
    def stopping(self) -> bool:
        """正在顿帧。Match 每帧拿它去压时间倍速。"""
        return self.hit_stop > 0.0

    def strike(self, hit: Hit) -> None:
        """一下打完了。这是所有命中的唯一入口。"""
        add_ring(
            self._particles, hit.position, hit.color, RING_LIFETIME,
            RING_RADIUS_BASE + math.sqrt(hit.total_damage) * RING_RADIUS_PER_SQRT_DAMAGE,
        )
        self._camera.shake(self.shake_amount(hit))
        for damage in hit.damages:
            add_number(self._particles, damage.position, damage.amount, damage.color)
        if hit.collision:
            # 两个角色撞上才顿帧，技能命中不顿：撞上是双方对等的"撞了个满怀"，
            # 挨刀挨锤是单方面在挨打，顿下来只显得拖
            #
            # 取 max 不累加：连着撞两下不该叠成半秒的慢动作，那一下"顿"只是一下
            self.hit_stop = max(self.hit_stop, HITSTOP_SECONDS)
        # 音效以后加在这儿

    def shake_amount(self, hit: Hit) -> float:
        """这一下该抖多重。公式和理由见文件开头。"""
        amount = SHAKE_ON_IMPACT if hit.collision else SHAKE_ON_HIT
        # 伤害项：掉到 SHAKE_DAMAGE_REFERENCE 那么多，抖动翻倍，再多封顶
        amount *= 1.0 + min(1.0, hit.total_damage / SHAKE_DAMAGE_REFERENCE)
        # 速度项：撞得越快越狠，加满也只是基础值的一半——速度是用来分辩轻重的，
        # 不是用来定生死的（真正定生死的是伤害那一项）
        amount *= 1.0 + SHAKE_SPEED_SHARE * min(
            1.0, hit.speed / SHAKE_SPEED_REFERENCE
        )
        if hit.collision:
            amount += SHAKE_EXTRA_COLLISION
        if hit.knockback > 0.0:
            amount += SHAKE_EXTRA_KNOCKBACK * min(
                1.0, hit.knockback / SHAKE_KNOCKBACK_REFERENCE
            )
        return amount

    def jolt(self, amount: float) -> None:
        """不伴随命中的一次单独震动。

        给那些"不是打中了谁、但就是该顿一下"的时刻用：幻影刺客起手挥砍、
        吸住咬合。它们自己知道该多重，这里只负责抖。
        """
        self._camera.shake(amount)

    def update(self, dt: float) -> None:
        self.hit_stop = max(0.0, self.hit_stop - dt)

    def reset(self) -> None:
        self.hit_stop = 0.0
