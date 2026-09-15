"""武士：一把绕身刀 + 一记穿刺。

和别的角色不太一样的地方在于它有**两个技能**——一个常驻被动、一个主动。
角色基类只有一栏 skill，所以被动挪到了 Character.passive 上（见 base.py 的
attach_passives）：主动技能要占技能条、要走冷却，被动不占条、也不"放"，
两者的生命周期完全不同，塞进同一栏反而要到处判"这个技能是不是被动的"。

碰撞效果本身仍然走基类默认的那套：弹开，不掉血。武士的输出全在刀和穿刺上。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Samurai(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
