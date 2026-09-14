"""吸血鬼：撞上对手不再弹开，而是吸住对方持续吸血。

这个角色是"碰撞效果可以被覆盖"的示范：基类只主张弹开，它把弹开换成
"吸住 + 持续吸取"，并顺带封住对方的技能。

数值不在这里，在 game/config_characters.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Character, CollisionOutcome

if TYPE_CHECKING:
    from ..ball import Ball


@dataclass(frozen=True)
class Vampire(Character):
    """覆盖 on_collision：不要弹开，改成吸住。"""

    latch_seconds: float = 5.0         # 吸住持续秒数
    drain_per_second: float = 10.0     # 吸住期间每秒从对方身上吸走多少血

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """主张"抓取"和"沉默"两件事，都不带撞击伤害。

        抓取只顶替弹开：两球不弹开，改成粘住持续吸取。撞上的这一瞬间不额外
        扣血——吸血鬼的输出全在"吸"上，不在"撞"上。

        沉默是单独一项，不跟着抓取走——虽然吸血鬼两个一起用，但机制上是分开的：
        抓取（连体位移）和沉默都只是通用附加项，任何角色都能只取其一。详见
        CollisionOutcome 的说明。

        想让它撞人也掉血的话，在这里填 damage_to_other——别去翻基类，
        撞击伤害不是基类给的。
        """
        return CollisionOutcome(
            grab_seconds=self.latch_seconds,
            grab_drain_per_second=self.drain_per_second,
            silences=True,
        )
