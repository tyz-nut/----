"""角色基类，以及"角色怎么参与碰撞结算"的约定。

角色 = 数据（尺寸、血量、技能）+ 行为（撞上对手时发生什么）。
默认行为写在基类里，子类只覆盖自己想改的那部分。

技能（Skill 及其子类）在 skills.py，这里只管碰撞这一侧。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .skills import Skill

if TYPE_CHECKING:
    from ..ball import Ball


@dataclass(frozen=True)
class CollisionOutcome:
    """角色对"撞上对手"这件事的主张。

    默认主张是"弹开 + 按自身移速伤对方"。下面三样都是**可选附加项**，
    彼此独立，角色想用哪样用哪样：

    - grab_seconds > 0：改为抓住对方。**弹开**被顶替掉（双方都不弹开，改成
      粘成一团一起飞 + 持续吸取），但 damage_to_other 照常结算——抓取只顶替
      弹开，不免除伤害。
    - silences：封住对方的技能。

    抓取和沉默互不依赖：可以只抓不封，也可以只封不抓（以后一个"禁魔"技能
    大概就是后者）。吸血鬼当前两个都用了。
    """

    damage_to_other: float = 0.0
    grab_seconds: float = 0.0            # > 0 表示吸住对方这么久
    grab_drain_per_second: float = 0.0   # 吸住期间每秒吸取对方多少血
    silences: bool = False               # 是否封住对方的技能

    @property
    def grabs(self) -> bool:
        return self.grab_seconds > 0


@dataclass(frozen=True)
class Character:
    """角色基类。

    子类通过覆盖 on_collision 改变碰撞效果，通过新增字段描述自己要用的参数。
    什么都不覆盖（如 normal.NormalBall）就是"默认角色长什么样"的说明。
    """

    id: str
    name: str
    radius: int
    max_hp: float
    description: str          # 角色卡上的第二行小字
    skill: Skill
    # 撞击伤害 = 撞上瞬间的自身移速的**平方** × 该系数。0 就是"不靠撞击输出"。
    # 覆盖了 on_collision 的角色只要还调用 super()，这个字段对它一样有效
    # （吸血鬼就是这么做的），填了不会白填。
    impact_damage_per_speed_sq: float = 0.0

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """默认碰撞效果：按自身移速伤对方，随后弹开。

        只看 ball 自己的速度，不看对方——所以谁撞得猛谁打得更疼。
        因为是平方，快球和慢球的差距被拉得很开：速度翻倍伤害变四倍。
        加速技能因此不只是"跑得快"，它本身就是伤害放大器。

        other 是留给子类的参数（比如吸血鬼不需要看它，但别的角色可能要）。
        """
        speed = ball.speed
        return CollisionOutcome(
            damage_to_other=speed * speed * self.impact_damage_per_speed_sq
        )
