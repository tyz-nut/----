"""激光：碰撞效果无，全靠墙上画出来的那些线输出。

和渔夫一样，这个类**一个方法都不覆盖**——存在只是为了说明"碰撞效果无"长什么样：
走基类的默认碰撞效果，正常弹开、不掉血。

它的技能是被动的（LaserSkill），所以这里没有 on_collision 可写：撞人不产生
任何效果，输出全部来自"撞墙"这件事——那条路径在 Ball.record_wall_hit 和
Match.apply_lasers 上。

数值不在这里，在 game/config_characters.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Laser(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
