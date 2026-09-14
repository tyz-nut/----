"""普通小球：最朴素的角色。

它不覆盖任何行为——碰撞效果和技能都直接用基类的默认实现。
换句话说，这个文件既是"默认角色"，也是写新角色时的参照物。

数值不在这里，在 game/config_characters.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class NormalBall(Character):
    """只填数据，不加行为。"""
