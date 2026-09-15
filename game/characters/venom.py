"""毒刺：碰撞效果无，输出全在撞墙留下的那些刺上。

和蜘蛛、激光一样，这个类**一个方法都不覆盖**——存在只是为了说明"碰撞效果无"
长什么样：走基类的默认碰撞效果，正常弹开、不掉血。

它的两个技能一被动一主动（刺 + 毒发），所以撞人不产生任何效果，输出全部来自
"撞墙"这件事——那条路径在 Ball.plant_spike 和 Match.apply_spikes 上。技能2
打多少也完全看对手身上中了几层毒，跟碰撞无关。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class VenomSting(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
