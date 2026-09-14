"""吸血鬼：撞上对手不再弹开，而是吸住对方持续吸血。

这个角色是"碰撞效果可以被覆盖"的示范：它把基类的默认主张
（弹开 + 按移速造成伤害）整个换成了"吸住 + 持续吸取"。

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
    """覆盖 on_collision：不要弹开，也不要撞击伤害，改成吸住。"""

    latch_seconds: float = 5.0         # 吸住持续秒数
    drain_per_second: float = 10.0     # 吸住期间每秒从对方身上吸走多少血

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """在默认碰撞效果之上，追加"抓取"和"沉默"两个主张。

        抓取只顶替弹开：两球不弹开，改成粘住持续吸取。撞击伤害照常结算，
        所以被抓住的一方贴上的一瞬间仍然打得出那一下。

        沉默是单独一项，不跟着抓取走——虽然吸血鬼两个一起用，但机制上是分开的：
        抓取（连体位移）和沉默都只是通用附加项，任何角色都能只取其一。详见
        CollisionOutcome 的说明。

        撞击伤害直接沿用基类算好的那份，不自己重写一遍——这样
        config_characters.py 里的 impact_damage_per_speed_sq 对这个角色同样有效
        （当前没填，也就是 0，吸血鬼不靠撞击输出；想让它也撞人掉血，填那个数即可）。
        """
        default = super().on_collision(ball, other)
        return CollisionOutcome(
            damage_to_other=default.damage_to_other,
            grab_seconds=self.latch_seconds,
            grab_drain_per_second=self.drain_per_second,
            silences=True,
        )
