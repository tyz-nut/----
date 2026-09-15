"""死灵法师：撞人按对方**已损**的血量咬一口，隔一阵子再来一场黑夜。

两个技能的分工很清楚，而且是配套的：

- 碰撞伤害按对方已损血量算，所以对方越残越疼。满血撞上去是 0——它不是一个
  用来削血的技能，是一个**收割**的技能。
- 黑夜降临把双方的位置和血量对调。所以残血的时候开黑夜，残的是对方。

两条合起来就是一个"先把你打残、再跟你换"的角色：自己撞人不太掉血（收割伤害
在对方满血时是 0），但对方一旦被别的东西磨下去，撞一下就很疼；真被压到残血
了，一场黑夜又把自己换回健康。

碰撞效果覆盖在 on_collision 里；黑夜是主动技能（NightfallSkill），走 skill
那一栏，占技能条。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Character, CollisionOutcome


@dataclass(frozen=True)
class Necromancer(Character):
    """碰撞效果：按对方已损血量的比例造成伤害。

    只在碰撞的那一瞬间结算一次（走 CollisionOutcome.damage_to_other，和普通
    小球的撞击伤害是同一条路），所以它是弹开之外多出来的一下，不是替代弹开。
    """

    missing_hp_damage_ratio: float = 0.0    # 伤害 = 对方已损血量 × 这个系数

    def on_collision(self, ball, other) -> CollisionOutcome:
        return CollisionOutcome(
            damage_to_other=other.missing_hp * self.missing_hp_damage_ratio
        )
