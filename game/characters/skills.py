"""特殊技能。

和碰撞效果同一套思路：Skill 是基类，具体技能是子类；数值写在
config_characters.py，行为写在这里。加技能 = 在本文件加一个类，
再到 config 里给角色挑一个。

技能自己**不保存状态**——它只负责"放出来的时候对球做什么"，
之后怎么持续生效由 Ball / Match 按球上的状态去算。这样技能可以是
无状态的 frozen dataclass，两个角色共用同一份实例也不会串。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pygame.math import Vector2

if TYPE_CHECKING:
    from ..ball import Ball
    from ..match import Match


@dataclass(frozen=True)
class Skill:
    """技能基类：一个名字 + 一个冷却 + 一个持续时间。

    duration 是**技能生效多久**，不是冷却。两种形态的分水岭：

    - duration = 0（默认）：一次性技能，放出来的一瞬间效果就结算完了，
      立刻进冷却。加速就是这种——涨那一档是瞬时的，"永久生效"说的是加速
      本身不掉，不是技能还在生效中。
    - duration > 0：持续型技能，先走完这段生效时长，**这段时间不计冷却**，
      等它结束了冷却才从 0 开始走。蝙蝠圈就是这种。

    两者在技能条上是两根不同方向、不同颜色的条，见 app.Game.skill_display。
    """

    name: str
    cooldown: float
    duration: float = 0.0

    def ready(self, ball: Ball) -> bool:
        """除了冷却好了，还有没有别的条件挡着不让放。默认没有。"""
        return True

    def active(self, ball: Ball) -> bool:
        """技能是不是还在生效中。

        默认就是看球上那个倒计时。一次性技能不设倒计时，所以永远返回 False，
        放完立刻进冷却。

        **生效时长不由时间决定的技能必须覆盖它**——钩锁就是：它要一直"生效"
        到钩中人为止，可能飞一秒也可能飞十秒，没法用一个秒数预先写出来。
        这种技能自己往球上挂一个状态（钩锁挂的是 ball.hook），然后在这里
        如实回答，等它结束时再让 Match 调 ball.finish_skill() 收尾。
        """
        return ball.skill_active_remaining > 0

    def activate(self, ball: Ball, match: Match) -> None:
        """放出来是什么效果。子类必须覆盖。"""
        raise NotImplementedError

    def on_wall_hit(self, ball: Ball, match: Match, point, side: str) -> None:
        """球撞墙了。默认什么都不做。

        这是给**被动技能**留的口子：主动技能由 cast_ready_skills 每隔一段冷却
        放一次，而被动技能的条件是"发生了某件事"。挂在这里之后，Match 不需要
        知道场上有哪些被动——它只管在球撞墙的时候喊一声，谁想听谁听。

        point 是墙面上的撞点，side 是哪一面墙（见 laser.py 的四个常量）。
        """
        return


@dataclass(frozen=True)
class BoostSkill(Skill):
    """加速：每释放一次就永久涨一档，冷却好了再放就再涨一档。

    每档加的是**绝对值**：出生速度 × spawn_speed_gain（0.5 就是半条出生速度）。
    因为它跟当前速度无关，所以是线性叠加——被撞慢下来之后，加的仍然是那么多，
    不会像"每次乘 2"那样越滚越快。
    """

    spawn_speed_gain: float = 0.5

    def activate(self, ball: Ball, match: Match) -> None:
        ball.add_boost(self.spawn_speed_gain)


@dataclass(frozen=True)
class BatSwarmSkill(Skill):
    """化作蝙蝠：以自己为圆心张开一圈，圈内的敌人被减速并持续吸取。

    圈跟着自己走，敌人离开圈立刻恢复（减速不残留）。这一路吸取和碰撞后
    吸住的那一路互不干扰，可以同时生效。

    圈的存活时间就是基类那个 duration——圈自己不另记倒计时，见 Ball.finish_skill。
    """

    radius: float = 170.0          # 圈的半径（像素）
    duration: float = 5.0          # 持续秒数（覆盖基类的 0：这是持续型技能）
    slow_ratio: float = 0.5        # 圈内敌人减速比例，0.5 就是速度砍半
    drain_per_second: float = 25.0  # 每秒从圈内敌人身上吸走多少血

    def activate(self, ball: Ball, match: Match) -> None:
        ball.start_aura(
            radius=self.radius,
            slow_ratio=self.slow_ratio,
            drain_per_second=self.drain_per_second,
        )


@dataclass(frozen=True)
class HookSkill(Skill):
    """抛钩：自己定在原地，朝当前朝向甩出一条会弹墙的钩锁。

    钩锁出去之后：

    - 渔夫不动，而且获得**霸体**——别人撞上来会被原路弹回，推不动他。
      霸体只顶替"被推动"这件事，撞击伤害照常结算（所以高速撞上来的小球
      会把自己撞伤在渔夫身上，而渔夫自己造成 0 伤害）。
    - 钩锁一路弹墙，直到钩中人为止（**没有超时**，见 ready 的说明）。
    - 钩中之后，对方沿钩锁走过的那条路被原路拖回来，路上持续掉血；
      拖的过程中两人不算碰撞。
    - 拖到身前，两人相互推开，技能结束、开始进冷却。

    这类技能没有 duration：它要飞多久完全看什么时候钩到人，预先写不出来。
    所以覆盖 active()，靠 ball.hook 回答"还在生效吗"，结束时由 Match 收尾。
    """

    hook_speed: float = 900.0        # 钩锁飞出去的速度（像素/秒）
    pull_speed: float = 800.0        # 收线速度（像素/秒）
    drain_per_second: float = 30.0   # 收线期间每秒从敌人身上吸走多少血
    reel_gap: float = 8.0            # 拉到身前时两球之间留的空隙（像素）

    def ready(self, ball: Ball) -> bool:
        """钩锁只有一条：手上还挂着一条就不能再甩。

        冷却时间其实管不住这件事——钩锁可能飞得比冷却还久，光靠冷却的话
        冷却一走完他就会甩出第二条，而第一条还在天上。
        """
        return ball.hook is None

    def active(self, ball: Ball) -> bool:
        return ball.hook is not None

    def activate(self, ball: Ball, match: Match) -> None:
        ball.cast_hook(
            hook_speed=self.hook_speed,
            pull_speed=self.pull_speed,
            drain_per_second=self.drain_per_second,
            reel_gap=self.reel_gap,
        )


@dataclass(frozen=True)
class LaserSkill(Skill):
    """激光：彻底被动的技能——没有冷却，也不会被"释放"。

    撞墙就留一个位点，攒够两个不同朝向的位点就连成一条激光，敌人碰到线持续
    掉血、多根叠加。线画出来就永久留在场上，不封顶。

    这个技能把 ready 直接钉死成 False：`cast_ready_skills` 是靠 skill_ready
    来判断"该不该放"的，而被动技能永远不该被它放出来——硬要是把 cooldown 填 0
    让它每帧都"放"一次，那也只是空转，不如明说。

    所以激光**不占技能条的那两根条**（它既没有冷却也没有生效时长）。条上写
    什么由 app.skill_display 单独接管，见那里的说明。它的效果全部走
    on_wall_hit，由 Match 在球撞墙的时候喊。
    """

    damage_per_second: float = 25.0    # 压在一条线上每秒掉多少血（多根会叠加）

    def ready(self, ball: Ball) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """被动技能没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("激光是被动技能，不该被 activate")

    def on_wall_hit(self, ball: Ball, match: Match, point: Vector2,
                    side: str) -> None:
        ball.record_wall_hit(point, side, self.damage_per_second)
