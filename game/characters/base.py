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

    子类通过覆盖 on_collision 描述自己的碰撞效果，通过新增字段描述自己要用的
    参数。什么都不覆盖（如 fisher.Fisher）就是"撞人只弹开、没有任何效果"。

    撞击伤害不在这里——它是普通小球独有的碰撞效果，字段和算法都在
    normal.NormalBall 上。基类不预设任何角色"该不该撞人掉血"。
    """

    id: str
    name: str
    radius: int
    max_hp: float
    description: str          # 角色卡上的第二行小字
    skill: Skill

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """默认碰撞效果：弹开，仅此而已。不掉血、不抓不封。

        弹开本身不经过这里（见 CollisionOutcome 的说明），所以返回一个空主张
        就是"什么都不附加"。

        other 是留给子类的参数（比如吸血鬼不需要看它，但别的角色可能要）。
        """
        return CollisionOutcome()
