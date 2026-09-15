"""望：碰撞效果无，输出全在战场被划成的那块棋盘上。

和蜘蛛、激光、毒刺一样，这个类**一个方法都不覆盖**——存在只是为了说明
"碰撞效果无"长什么样：走基类的默认碰撞效果，正常弹开、不掉血。

它的本事全在棋子上，跟撞人没关系。而且它连"撞墙"这条路都不走：激光、蛛丝、
毒刺的被动都是撞墙触发（on_wall_hit），望的棋是**按时间自己落**的，不需要
任何触发（见 skills.GoSkill）。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Lookout(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
