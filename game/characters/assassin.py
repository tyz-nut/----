"""幻影刺客：预判到要挨打了就闪到对方身后，跟着它的动量一路砍。

它和别的角色有个方向上的不同：别的角色都是"我想打你的时候做点什么"，它是
"你要打我的时候我先走"。所以它的技能不是玩家按出来的——冷却好之后由技能
自己盯着场上的动向，等真要撞上了才放（见 skills.BlinkStrikeSkill.ready 和
core/predict.py）。

碰撞上它什么都没有：撞上了就按普通小球的规矩弹开，没有额外伤害、没有附加
状态。它全部的本事都在那一闪里。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character


@dataclass(frozen=True)
class PhantomAssassin(Character):
    """碰撞效果：无。闪避交给技能，撞击就是普通的弹开。"""
