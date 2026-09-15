"""大锤：一把锤子绕着自己抡，砸中就把人打飞。

这个类**一个方法都不覆盖**——和蜘蛛、渔夫、激光一样，撞人不产生任何效果
（走基类的默认碰撞效果：正常弹开、不掉血）。存在只是为了说明"碰撞效果无"
长什么样，以及把大锤和其他几个"输出不在碰撞上"的角色摆在一起看。

它的全部输出在那个被动技能上（HammerSkill），所以这里没有 on_collision 可写：
撞人只是撞人，真打人的是锤子。装锤子走 Character.attach_passives → on_spawn
那条路，和武士的绕身刀是同一条。

它和武士那把刀最值得对照的一点：**刀是蹭血，锤子是打飞**。刀刮一下对方照原
样飞，锤子砸一下对方的速度被整个重写。两者的几何几乎一样（都是绕着自己转的
一条线段 + 每圈一次），差别全在命中之后那一下上，所以物理模型单独写在
game/states/hammer.py 的开头。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class Hammer(Character):
    """碰撞走基类默认行为：弹开，不造成伤害。"""
