"""渔夫：碰撞效果无，输出来自钩锁。

这个角色是"什么都不用覆盖"的示范——它的碰撞效果就是基类的默认行为：
正常弹开，不掉血、不抓不封。

所以不需要覆盖 on_collision。这个类存在的意义是给这个角色一个说明自己的
地方，以及以后要改时有个落脚点。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Fisher(Character):
    """不覆盖任何东西——这就是一个"碰撞效果为无"的角色。"""
