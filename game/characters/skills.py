"""特殊技能。

和碰撞效果同一套思路：Skill 是基类，具体技能是子类；数值写在
config/roster.py，行为写在这里。加技能 = 在本文件加一个类，
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
    from ..core.ball import Ball
    from ..core.match import Match


@dataclass(frozen=True)
class Skill:
    """技能基类：一个名字 + 一个冷却 + 一个持续时间。

    duration 是**技能生效多久**，不是冷却。两种形态的分水岭：

    - duration = 0（默认）：一次性技能，放出来的一瞬间效果就结算完了，
      立刻进冷却。加速就是这种——涨那一档是瞬时的，"永久生效"说的是加速
      本身不掉，不是技能还在生效中。
    - duration > 0：持续型技能，先走完这段生效时长，**这段时间不计冷却**，
      等它结束了冷却才从 0 开始走。蝙蝠圈就是这种。

    两者在技能条上是两根不同方向、不同颜色的条，见 ui/app.Game.skill_display。
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

    def on_spawn(self, ball: Ball, match: Match) -> None:
        """球出生了（开局、换角色、重开都会走到这里）。默认什么都不做。

        给**常驻被动**用的口子：激光那种被动是"撞墙的时候"才有反应，而武士
        那把刀从出生起就一直在转，没有"触发"这回事，得有个地方把它挂上去。

        在 Match 建好球之后调用，所以技能可以直接往球上写状态。
        """
        return

    def on_wall_hit(self, ball: Ball, match: Match, point, side: str) -> None:
        """球撞墙了。默认什么都不做。

        这是给**被动技能**留的口子：主动技能由 cast_ready_skills 每隔一段冷却
        放一次，而被动技能的条件是"发生了某件事"。挂在这里之后，Match 不需要
        知道场上有哪些被动——它只管在球撞墙的时候喊一声，谁想听谁听。

        point 是墙面上的撞点，side 是哪一面墙（见 core/arena.py 的四个常量）。
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


@dataclass(frozen=True)
class WebSkill(Skill):
    """结网：撞一次墙就在墙上钉一个锚点，从自己身上拉一根丝过去。

    和激光同属**触发式被动**（走 on_wall_hit，ready 钉死成 False，不占技能条），
    但两者的线完全不是一回事：

    - 激光要撞够**两面不同的墙**才连出一条，那条线两端都钉在墙上，跟人无关。
    - 蛛丝撞一下就出一根，而且**一头永远连着自己**——球跑到哪，丝就扫到哪。

    所以蛛丝的威胁范围是"以自己为顶点的一把扇子"，而不是"场地上几条固定的
    线"。代价是刚钉下的那一下丝只有一个半径长，得跑开才拉得开。

    敌人压上任何一根丝都会被减速并持续掉血，**多根叠着碰到就叠着算**。
    """

    damage_per_second: float = 20.0   # 压在一根丝上每秒掉多少血（多根会叠加）
    slow_ratio: float = 0.4           # 压在一根丝上减速多少，0.4 就是速度打六折

    def ready(self, ball: Ball) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """被动技能没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("结网是被动技能，不该被 activate")

    def on_wall_hit(self, ball: Ball, match: Match, point: Vector2,
                    side: str) -> None:
        ball.anchor_web(point, self.damage_per_second, self.slow_ratio)


@dataclass(frozen=True)
class NightfallSkill(Skill):
    """黑夜降临：战场黑一下，黑到底的那一瞬双方互换位置与血量。

    **这个技能和别的技能不一样的地方在于它改的是 Match 而不是自己**：黑屏盖的是
    整块战场，换位动的是两颗球，没有一样是"挂在这颗球身上的状态"。所以它不往
    ball 上写任何东西，只调 match.start_darkness，之后由 Match 自己推进（见
    Match.update_darkness）。技能条走的还是通用那套——它有 duration，所以是
    "先黄条（正在黑）后蓝条（冷却）"的持续型技能。

    黑屏和换位是同一根时间轴上的两件事，对上关系见 darkness.py：换位卡在渐暗
    走完的那一瞬，藏在那片黑里。

    **换不换是"放的人说了算"的**：只有放技能这位自己的血量百分比低于对手时才
    真的换，否则黑屏照播、场面纹丝不动（纯演出）。所以这一场黑夜得记住是谁放的
    ——caster 跟着 Darkness 走，见 Match.start_darkness。

    换位换什么、不换什么（尤其是霸体和被吸住的时候怎么办），写在
    Match.nightfall_swap 上——那是这一整套里唯一真正需要想清楚的地方。
    """

    duration: float = 1.2    # 整段黑屏几秒。三段的比例在 config/settings.py

    def activate(self, ball: Ball, match: Match) -> None:
        match.start_darkness(self.duration, ball.player)


@dataclass(frozen=True)
class HammerSkill(Skill):
    """巨锤：一把锤子一直在自己身边抡，砸中就把敌人打飞。

    和绕身刀同属**常驻被动**（从出生起就在抡，起点是 on_spawn，ready 钉死成
    False，不占技能条），几何也几乎一样，但打中之后干的事完全不同：

    - 刀是"蹭一下扣一次血"，对方该怎么飞还怎么飞。
    - 锤子是**打飞**：对方的速度被整个重写。

    那个"飞"不是随手加一股冲量，是**对方撞上了一面正在移动的、无限质量的墙**
    的完全弹性碰撞结果（v' = 2u - v，u 是锤头速度）。整套推导和"为什么它不
    守恒动量"写在 states/hammer.py 的开头，这里只管把数值挂上去。

    伤害同理，按锤头与敌人的**相对**速度平方算——伤害系数那一项也在那边解释。

    打不飞的情况只有一种：对方是**霸体**（甩着钩锁的渔夫、被吸住的球）。霸体
    顶替的是"被推动"，所以那一锤**照样掉血，只是纹丝不动**——和渔夫那条
    "霸体只顶替被推动、伤害照常两边各算各的"是同一条原则。

    它不占技能条（和刀一样，角色只有一根条）：锤子的转速、长度、当前锤头有
    多快都不是"进度"，画成条没意义。大锤这个角色就这一个被动，条上写什么由
    app.hammer_display 单独接管。
    """

    angular_speed: float = 3.2       # 角速度（弧度/秒）。一圈约 2 秒
    inner_radius: float = 20.0       # 柄的内端离球心多远（贴着球面）
    outer_radius: float = 72.0       # 柄的外端，也就是锤头中心离球心多远
    head_radius: float = 16.0        # 锤头多大。判定用的是它，不是球半径
    damage_per_speed_sq: float = 0.0006   # 伤害 = 相对速度² × 这个系数

    def ready(self, ball: Ball) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """常驻被动没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("巨锤是被动技能，不该被 activate")

    def on_spawn(self, ball: Ball, match: Match) -> None:
        ball.start_hammer(
            angular_speed=self.angular_speed,
            inner_radius=self.inner_radius,
            outer_radius=self.outer_radius,
            head_radius=self.head_radius,
            damage_per_speed_sq=self.damage_per_speed_sq,
        )


@dataclass(frozen=True)
class BladeSkill(Skill):
    """绕身刀：一把刀一直绕着球转，蹭到敌人扣一次血，每转一圈最多蹭一次。

    这是**常驻被动**：不像激光那样等着某件事发生，从球出生的那一刻就在转，
    所以起点是 on_spawn 而不是 activate（它永远不会被"放"，ready 也钉死成
    False，理由和 LaserSkill 一样）。

    它不占技能条——一个角色只有一根条，给武士占着的是穿刺。刀的转速和伤害
    都不是"进度"，画成条也没意义，所以它整个不在条上，只在战场上看得见。
    """

    angular_speed: float = 4.0       # 角速度（弧度/秒）。一圈约 1.6 秒
    inner_radius: float = 18.0       # 刀刃内端离球心多远（贴着球面）
    outer_radius: float = 46.0       # 刀刃外端。两个数一起决定刀有多长
    damage: float = 45.0             # 蹭一下扣多少血

    def ready(self, ball: Ball) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """常驻被动没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("绕身刀是被动技能，不该被 activate")

    def on_spawn(self, ball: Ball, match: Match) -> None:
        ball.start_blade(
            angular_speed=self.angular_speed,
            inner_radius=self.inner_radius,
            outer_radius=self.outer_radius,
            damage=self.damage,
        )


@dataclass(frozen=True)
class ThrustSkill(Skill):
    """穿刺：朝敌人锁死一个方向，用极快的速度直线冲一段距离。

    出手的瞬间做三件事：锁定方向（这一刻指向敌人）、记住冲完要接着走多快、
    把这一下要打的伤害带上路。之后这几帧球归 Match.update_thrusts 管。

    能不能打中看两件事，都是**冲刺途中持续判**的：

    - 敌人还在不在那条线上。方向出手时就锁死了，所以敌人跑得快就能在冲过去
      之前让开——这是这个技能最要紧的一条：它不是一个必中的锁定技。
    - 敌人离得够不够近。冲的距离是有限的，敌人站得太远，冲到头也够不着。

    够着了就**停在对方身前**收招，不接着冲完剩下的距离。冲刺期间**不算碰撞**
    （见 Match.resolve_collision）：这一下从头到尾由穿刺自己结算，不顶开对方，
    也不被对方顶开。
    """

    thrust_speed: float = 1800.0     # 冲刺速度（像素/秒）。比正常移速快好几倍
    thrust_distance: float = 320.0   # 一次冲多远（像素）。撞墙就在墙前停下
    damage: float = 120.0            # 冲到了扣这么多，一次穿刺只扣一下

    def activate(self, ball: Ball, match: Match) -> None:
        ball.start_thrust(
            match=match,
            speed=self.thrust_speed,
            distance=self.thrust_distance,
            damage=self.damage,
        )
