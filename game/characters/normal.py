"""普通小球：唯一靠"撞人"输出的角色。

它的碰撞效果是自己写的：撞上对方的瞬间按自身移速的平方扣对方血。
这是**这个角色独有的**，不是所有角色的底子——基类的默认碰撞效果只是弹开，
另外三个角色（吸血鬼、渔夫、激光）撞人都不掉血。

数值不在这里，在 game/config_characters.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Character, CollisionOutcome

if TYPE_CHECKING:
    from ..ball import Ball


@dataclass(frozen=True)
class NormalBall(Character):
    """碰撞效果：按自身移速伤对方，再弹开。

    技能走通用的加速，不在这里。
    """

    # 撞一次掉的血 = 撞上瞬间的自身移速的**平方** × 这个系数
    impact_damage_per_speed_sq: float = 0.0

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """按自身移速的平方伤对方。

        只看 ball 自己的速度，不看对方——所以谁撞得猛谁打得更疼。因为是平方，
        快球和慢球的差距被拉得很开：速度翻倍伤害变四倍。加速技能因此不只是
        "跑得快"，它本身就是伤害放大器。
        """
        speed = ball.speed
        return CollisionOutcome(
            damage_to_other=speed * speed * self.impact_damage_per_speed_sq
        )
