"""蜘蛛：碰撞效果无，输出全在撞墙拉出来的那些丝上。

这个类**一个方法都不覆盖**——存在只是为了说明"碰撞效果无"长什么样：走基类的
默认碰撞效果，正常弹开、不掉血。和渔夫、激光一样。

它的技能是被动的（WebSkill），所以这里没有 on_collision 可写：撞人不产生任何
效果，输出全部来自"撞墙"这件事——那条路径在 Ball.anchor_web 和 Match.apply_webs
上。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Spider(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
