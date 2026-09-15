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
    from ..core.ball import Ball


@dataclass(frozen=True)
class CollisionOutcome:
    """角色对"撞上对手"这件事的主张。

    **撞上一定弹开**，这是碰撞的底子，不在这个主张里——主张说的是弹开之外
    还要额外发生什么。三样附加项彼此独立，角色想用哪样用哪样，都不填就是
    "只弹开"：

    - damage_to_other > 0：这一下伤对方这么多血。想按什么算由角色自己定，
      CollisionOutcome 只收算好的数（普通小球按移速平方算，见 normal.py）。
    - grab_seconds > 0：抓住对方。**弹开**被顶替掉（双方都不弹开，改成粘成
      一团一起飞 + 持续吸取），但 damage_to_other 照常结算——抓取只顶替弹开，
      不免除伤害。
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

    子类通过覆盖 on_collision 描述自己的碰撞效果，通过新增字段描述自己要用的参数。
    默认只弹开。
    """

    id: str
    name: str
    radius: int
    max_hp: float
    description: str          # 角色卡上的第二行小字
    skill: Skill
    passive: Skill | None = None   # 常驻被动，不占技能条。没有就是 None

    def attach_passives(self, ball: Ball, match) -> None:
        """造球的时候把生来就有的东西挂上去。两栏都问一遍，没有的什么都不做。

        和 skill 的区别：skill 是"冷却好了放一次"的主动技能，由 Match 每隔
        一段时间问一次；passive 是生来就有的东西（绕身刀），只在出生这一下
        装好，之后它自己一直在。所以这里不是"放技能"，是"装配件"。

        **两栏都要问**，因为常驻的东西不保证放在 passive 那一栏：武士的绕身刀
        在 passive（它还有个主动的穿刺占着 skill），而激光、蜘蛛、大锤那种
        "整个角色就一个被动、没有主动技能"的，被动是直接填在 skill 上的。
        只问 passive 的话，大锤的锤子永远挂不上去。on_spawn 默认什么都不做，
        所以主动技能被问一句也没有副作用。
        """
        self.skill.on_spawn(ball, match)
        if self.passive is not None:
            self.passive.on_spawn(ball, match)

    def on_wall_hit(self, ball: Ball, match, point, side: str) -> None:
        """球撞墙了，谁想听谁听。

        **两栏都要问**，理由和 attach_passives 一模一样：撞墙触发的被动不保证
        放在哪一栏——激光、蜘蛛那种"整个角色就一个被动、没有主动技能"的填在
        skill 上，而毒刺和武士一样有两栏：主动的毒发占着 skill，被动的刺填在
        passive。只问 skill 的话，毒刺的刺永远钉不上墙。

        以后再加"撞墙触发"的角色，照旧不用改这里——填哪一栏都会被问到。
        """
        self.skill.on_wall_hit(ball, match, point, side)
        if self.passive is not None:
            self.passive.on_wall_hit(ball, match, point, side)

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """默认碰撞效果：弹开
        """
        return CollisionOutcome()
