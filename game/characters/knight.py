"""骑士：国王召出来的小球。

它是一颗**完整的球**：有血量、按自己的动量飞、撞墙正常反弹、会被别人的技能
打到（用户定的"和普通球一样会中招"——激光、蛛丝、毒刺、刀、锤子、棋子、渔夫
的钩锁全都照常招呼它）。它和主球只差两点，两点都是同一个原因：**它不是玩家
选的那个角色本人**。

- 它和**自己这一边**（国王、国王的其它骑士）撞上只弹开、不掉血。"碰到自己
  不会互相造成伤害、但会发生碰撞"（用户定的）是这一边的内部规矩，不属于
  任何一颗球，所以写在 Match.resolve_summons_collisions 里。
- 它**不参与抓取**（吸血鬼那一套）。Latch 是"两球绑成一团连体位移"的机制，
  要的是一对稳定的两人组，掺进一颗召出来的兵会把合体速度、霸体、黑夜换位
  那一整套搅乱。所以吸血鬼抓不住骑士——钩锁倒是不受这条限制，它一钩就一钩，
  不需要"一对"这个前提。
- 它**不参与胜负、黑夜换位、重开重建**。这三件事只对"玩家选的那个角色本人"
  成立（骑士死光不算输），所以它们走的都是 Match.mains 而不是 combatants。

球上区分这两类的是 Ball.summoned。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Character, CollisionOutcome

if TYPE_CHECKING:
    from ..core.ball import Ball


@dataclass(frozen=True)
class Knight(Character):
    """碰撞效果：伤对方很多，自己也掉一点。

    和国王那一条正好是反过来的——国王是"伤敌少、自损多"，骑士是"伤敌多、
    自损少"。所以一批骑士撞上去是一笔划算的买卖，而国王本人撞上去是亏的。
    """

    collision_damage: float = 0.0        # 撞上敌人，敌人掉这么多
    collision_self_damage: float = 0.0   # 同一撞，自己也掉这么多

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        return CollisionOutcome(
            damage_to_other=self.collision_damage,
            damage_to_self=self.collision_self_damage,
        )
