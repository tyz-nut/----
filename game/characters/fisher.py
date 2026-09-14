"""渔夫：碰撞效果无，输出来自钩锁。

这个角色是"什么都不用覆盖"的示范——它的碰撞效果就是基类的默认行为，
也就是正常弹开、按自身移速造成伤害。区别只在于 config_characters.py 里
impact_damage_per_speed_sq 留着 0，于是伤害恒为 0，效果就变成
"正常弹开且不造成伤害"。

所以不需要覆盖 on_collision：基类算出来的 damage_to_other 本来就是 0。
这个类存在的意义是给这个角色一个说明自己的地方，以及以后要改时有个落脚点。

数值不在这里，在 game/config_characters.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Fisher(Character):
    """不覆盖任何东西——这就是一个"碰撞效果为无"的角色。"""
