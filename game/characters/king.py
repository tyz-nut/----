"""国王：撞人是亏本买卖，输出全靠召出来的骑士。

它走的还是普通小球那条路——碰撞伤害写在 on_collision 里——但**多了一个
damage_to_self**：撞上敌人伤对方一点、自己掉更多（用户定的）。所以它和普通
小球的正负完全相反：普通小球是"撞得越狠越赚"，国王是"撞上去就是亏"。

于是这个角色的打法是**不撞**：本体躲着走，让骑士去撞。骑士那一条（见
knight.py）正好是反过来的——伤敌多、自损少。两者是一套的。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Character, CollisionOutcome

if TYPE_CHECKING:
    from ..core.ball import Ball


@dataclass(frozen=True)
class King(Character):
    """碰撞效果：伤对方一点，自己掉更多。

    技能（召唤骑士）在 skills.KingSkill，数值在 roster。
    """

    collision_damage: float = 0.0        # 撞上敌人，敌人掉这么多（少）
    collision_self_damage: float = 0.0   # 同一撞，自己掉这么多（多）

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        return CollisionOutcome(
            damage_to_other=self.collision_damage,
            damage_to_self=self.collision_self_damage,
        )
