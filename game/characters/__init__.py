"""角色包：每个角色一个模块，类继承自 base.Character。

这里只有"行为"：角色怎么参与碰撞（base.py / normal.py / vampire.py），
以及技能放出来是什么效果（skills.py）。角色的数值全部集中在
game/config/roster.py —— 注册表也在那边，所以这个包不 import 它，
免得绕成循环导入。
"""

from .assassin import PhantomAssassin
from .base import Character, CollisionOutcome
from .fisher import Fisher
from .hammer import Hammer
from .laser import Laser
from .necromancer import Necromancer
from .normal import NormalBall
from .samurai import Samurai
from .skills import (
    BatSwarmSkill,
    BladeSkill,
    BlinkStrikeSkill,
    BoostSkill,
    HammerSkill,
    HookSkill,
    LaserSkill,
    NightfallSkill,
    Skill,
    ThrustSkill,
    VenomSpikeSkill,
    VirulenceSkill,
    WebSkill,
)
from .spider import Spider
from .vampire import Vampire
from .venom import VenomSting

__all__ = [
    "Character",
    "CollisionOutcome",
    "Skill",
    "BoostSkill",
    "BatSwarmSkill",
    "HookSkill",
    "LaserSkill",
    "BladeSkill",
    "ThrustSkill",
    "WebSkill",
    "NightfallSkill",
    "HammerSkill",
    "BlinkStrikeSkill",
    "VenomSpikeSkill",
    "VirulenceSkill",
    "NormalBall",
    "Vampire",
    "Fisher",
    "Laser",
    "Samurai",
    "Spider",
    "Necromancer",
    "Hammer",
    "PhantomAssassin",
    "VenomSting",
]
