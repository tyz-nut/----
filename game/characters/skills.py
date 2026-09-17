"""特殊技能。

和碰撞效果同一套思路：Skill 是基类，具体技能是子类；数值写在
config/roster.py，行为写在这里。加技能 = 在本文件加一个类，
再到 config 里给角色挑一个。

技能自己**不保存状态**——它只负责"放出来的时候对球做什么"，
之后怎么持续生效由 Ball / Match 按球上的状态去算。这样技能可以是
无状态的 frozen dataclass，两个角色共用同一份实例也不会串。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pygame.math import Vector2

from ..core.predict import will_be_hit
from ..states.hook import FishSpec

if TYPE_CHECKING:
    from ..core.ball import Ball
    from ..core.match import Match
    # 只在类型检查时 import：base 在运行时是 import 这个模块的（它要用 Skill），
    # 真 import 进来就绕成一个圈了
    from .base import Character


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

    def ready(self, ball: Ball, match: Match) -> bool:
        """除了冷却好了，还有没有别的条件挡着不让放。默认没有。

        要 match 是为了那些"看场上局势才决定放不放"的技能——幻影刺客的技能
        就是被动等着触发的，它得拿整局去预判自己是不是快撞上了（见
        core/predict）。绝大多数技能用不到，忽略即可。
        """
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
class IdleSkill(Skill):
    """没有技能。

    给骑士这种**纯召唤物**用的：Character 要求 skill 那一栏一定有东西，而骑士
    的本事全在碰撞里（见 characters/knight.py），它不冷却、不触发、也没有技能条。
    填一个空的 Skill 进去会留下一个 activate 抛 NotImplementedError 的坑——哪天
    有人把骑士也算进 cast_ready_skills，那一帧就会当场炸。所以这里明确地把
    ready 钉死成 False，activate 写成什么都不做：不是"忘了写"，是"本来就没有"。

    顺带一提，骑士确实走不到 cast_ready_skills：那一趟遍历的是场上**全部**
    单位，骑士也在里面，拦住它的正是这里这个 ready——所以这一栏钉死成 False
    不是保险，是那趟循环唯一的闸门。
    """

    def ready(self, ball: Ball, match: Match) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
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
    - 钩锁一路弹墙，但**鱼线是有限长的**：折线总长走到 line_length 还没钩到人
      就收场（见 Match.fly_hook / hook_missed）。所以它不再能站在角落里无限抛。
    - 钩中之后，对方沿钩锁走过的那条路被原路拖回来，路上持续掉血；
      拖的过程中两人不算碰撞。
    - 拖到身前，两人相互推开，技能结束、开始进冷却。

    **钩空不是白甩**（用户定的）：线放完还没咬到人，就在钩子落点那儿放一条鱼
    出去追人，体型随机、咬多重活多久都跟着体型走。不过**有一定概率连鱼都放不
    出来**（见 FishSpec.fail_chance）——那一档才是真的白甩一次。

    这类技能没有 duration：它要飞多久完全看什么时候钩到人，预先写不出来。
    所以覆盖 active()，靠 ball.hook 回答"还在生效吗"，结束时由 Match 收尾。

    **鱼放出来技能就收招了**（用户定的）：冷却从放鱼那一刻开始走，鱼之后在
    水里游多久、咬不咬得到，都跟这条技能没关系了——它是"放出去就不管了"的
    东西，和激光画在墙上的线、蛛丝、毒刺同一类（见 Ball.fishes）。
    """

    hook_speed: float = 900.0        # 钩锁飞出去的速度（像素/秒）
    pull_speed: float = 800.0        # 收线速度（像素/秒）
    drain_per_second: float = 30.0   # 收线期间每秒从敌人身上吸走多少血
    reel_gap: float = 8.0            # 拉到身前时两球之间留的空隙（像素）
    line_length: float = 900.0       # 鱼线总长（像素）。走到头还没钩到人就收场

    # 钩空之后那条鱼的全部参数（体型范围、每像素多少伤害、游速、召唤失败率）。
    # 打包成一整份而不是摊成七个字段：这一组数在放钩的那一刻是**整份**抄走的，
    # 摊开写的话每加一个数就要在这里、cast_hook 的签名、Match 的调用点各改一处
    fish: FishSpec = field(default_factory=lambda: FishSpec())

    def ready(self, ball: Ball, match: Match) -> bool:
        """钩锁只有一条：手上还挂着一条就不能再甩。

        冷却时间管不住这件事——钩锁可能飞得比冷却还久，光靠冷却的话冷却一走完
        他就会甩出第二条，而第一条还在天上。

        **鱼不在这个条件里**（用户定的）：鱼一放出来技能就收招了，冷却从那一刻
        开始走，所以技能这边不欠它什么。水里同时游着几条鱼是允许的。
        """
        return ball.hook is None

    def active(self, ball: Ball) -> bool:
        """生效中 = 手上还挂着钩锁。**鱼不算**（用户定的：召出鱼技能就进冷却）。

        这一条决定了技能条上画什么：不算鱼，钩空之后条上才会如实变成蓝色的
        "冷却 N 秒"，而不是继续黄着报那条鱼的剩余寿命。
        """
        return ball.hook is not None

    def activate(self, ball: Ball, match: Match) -> None:
        ball.cast_hook(
            hook_speed=self.hook_speed,
            pull_speed=self.pull_speed,
            drain_per_second=self.drain_per_second,
            reel_gap=self.reel_gap,
            line_length=self.line_length,
            fish_spec=self.fish,
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

    def ready(self, ball: Ball, match: Match) -> bool:
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

    def ready(self, ball: Ball, match: Match) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """被动技能没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("结网是被动技能，不该被 activate")

    def on_wall_hit(self, ball: Ball, match: Match, point: Vector2,
                    side: str) -> None:
        ball.anchor_web(point, self.damage_per_second, self.slow_ratio)


@dataclass(frozen=True)
class VenomSpikeSkill(Skill):
    """毒刺：撞一次墙就在墙上留一根毒刺，碰到的敌人挨一下并且中毒。

    和激光、蛛丝同属**触发式被动**（走 on_wall_hit，ready 钉死成 False，
    不占技能条），但三者的"留下的东西"完全不是一回事：

    - 激光要撞够**两面不同的墙**才连出一条线，那条线跟人再没关系。
    - 蛛丝撞一下出一根，**一头永远连着自己**，所以它会跟着人扫。
    - 毒刺撞一下出一根，**钉死在墙上**，但它是唯一会**反复触发**的：
      扎完一次过一会儿重新长好，同一根刺可以扎同一个人很多次。

    最后这条是这个角色的全部：刺不是一次性的地雷，是一台一直在出毒的机器。
    所以"叠毒"这件事不靠多钉几根，靠的是对手在刺旁边待多久——被逼到墙上、
    被钩过来、被刀逼着贴墙走，都会在几秒之内叠起好几层。

    刺**永久不封顶**（用户定的，同激光和蛛丝），蓄力间隔见 spike_cooldown。
    """

    spike_size: float = 16.0        # 刺有多"大"。判定上等于给对方的半径加这么多
    spike_damage: float = 40.0      # 扎到那一下的一次性伤害（就是普通命中那一下）
    spike_cooldown: float = 1.5     # 扎完一次要等这么久才能再扎
    poison_seconds: float = 6.0     # 每扎一次叠上去的那层毒活多久
    poison_per_second: float = 8.0  # 那一层每秒掉多少血。**层层叠加**

    def ready(self, ball: Ball, match: Match) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """被动技能没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("毒刺是被动技能，不该被 activate")

    def on_wall_hit(self, ball: Ball, match: Match, point: Vector2,
                    side: str) -> None:
        ball.plant_spike(
            point, side,
            size=self.spike_size,
            damage=self.spike_damage,
            poison_seconds=self.poison_seconds,
            poison_per_second=self.poison_per_second,
            cooldown=self.spike_cooldown,
        )


@dataclass(frozen=True)
class VirulenceSkill(Skill):
    """毒发：让对手身上此刻的毒一次性发作——伤人，并回自己的血。

    两样都按**对手当前的毒层数**涨，各带一个基础值：一层都没有时也放得出，
    只是那一下最轻（用户定的"有个基础伤害和回血量"）。所以这不是一个"没毒
    就白放"的技能——但它真正的收益全在层数上，层数高了才值得放。

    **只读不消耗**（用户定的）：层数照常按各自的倒计时走，这个技能只是
    "看一眼现在有几层"。所以毒叠上去就一直在高点，不存在"放完要重新叠"的
    节奏——它是一个把毒刺攒出来的优势兑成伤害和续航的出口，不是一个消耗品。

    回血报的是**实际**回的量（Ball.heal 的返回值）：满血时这一下回的是 0，
    飘个绿字就成了凭空多出来的数字。

    伤害走 Match.venom_burst，不在这里直接调特效——理由和 NightfallSkill
    调 match.start_darkness 一样：技能管数值，执行留给 Match。
    """

    base_damage: float = 40.0       # 0 层时也有的那一份
    damage_per_stack: float = 30.0  # 每一层再加这么多
    base_heal: float = 20.0
    heal_per_stack: float = 15.0

    def activate(self, ball: Ball, match: Match) -> None:
        target = match.opponent(ball)
        if target is None:
            return
        stacks = target.venom_stacks
        match.venom_burst(
            ball, target,
            damage=self.base_damage + self.damage_per_stack * stacks,
            heal=self.base_heal + self.heal_per_stack * stacks,
        )


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

    **黑屏的时候时间也会变慢**（slow_factor），而且只慢"渐暗 + 全黑"那一段，
    渐亮就恢复正常——所以那个换位卡在最慢、最黑的那一下里。减速写在这里、
    由 Darkness 带着走（见 states/darkness.py 的 slowing）。
    """

    duration: float = 1.2    # 整段黑屏几秒。三段的比例在 config/settings.py
    slow_factor: float = 0.35   # 黑屏期间游戏速度压到几倍（1 = 不压）

    def activate(self, ball: Ball, match: Match) -> None:
        match.start_darkness(self.duration, ball, self.slow_factor)


@dataclass(frozen=True)
class BlinkStrikeSkill(Skill):
    """闪现突袭：冷却好了**不马上放**，等着被撞的那一刻闪走。

    这是第一个"条件触发"的主动技能，和别的技能的分水岭在 ready：

    - 别的技能 ready 只管"还有没有别的条件挡着"（钩锁那句问的是"手上还有没有
      一条没回来"），冷却一到就放。
    - 这个技能的 ready 就是那个条件本身——它会去**预判**自己接下来一小段会不会
      撞上敌人或对方留下的东西（球、刀、锤、激光、蛛丝、飞在半路的钩锁），
      会撞才放。这个判断要读整局，所以 Skill.ready 才多收了一个 match 参数。

    于是"等待触发"这件事不需要任何新机制：cast_ready_skills 本来就在每帧问
    "能放吗"，让 ready 回答"暂时还不能"就行。玩家看到的观感是"冷却完了但技能
    没亮起来，等真要被撞了才闪出去"——技能条上那一段就是待发态。

    触发之后（见 Match.start_blink）是一整套**连招**：

    1. **闪到敌人身后**一段距离（身后 = 敌人运动方向的反面），砍一刀。
    2. 再**围着敌人随机挑一个方向**闪过去，砍一刀。
    3. 重复第 2 步，直到 slash_seconds 走完。

    第 1 步和后面几步的取位不一样是有讲究的：起手是"咬尾巴"，那是"我盯上你了"
    这个决定，得看得出来是从背后扑上去的；后面就是纯粹的乱刀，落点随机，对方
    读不出来下一刀从哪儿来（用户定的）。

    **砍的时候速度为 0**（用户定的）：挥砍期间刺客定在原地，位置全靠闪现换。
    这是它的代价——一整套乱刀必定命中（落点是刺客自己挑的），那就得拿"这几个
    时刻我动不了"来付账。唯一的例外是**被击退**：期间要是被外力推走了，收招的
    时候按那份速度走，而不是按常规那条"往敌人反方向离开"。

    所以结束条件只剩一个：时间走完，或者目标死了。**没有"拉开距离就收招"了**
    ——每一刀都闪到对方脸上，本来就拉不开（见 states/blink.py）。

    这类技能没有 duration（生效多久由连招自己数），靠覆盖 active() 回答，和
    钩锁同类。
    """

    cooldown: float = 12.0
    react_seconds: float = 0.32      # 往前预判多久。越大越早触发，也越容易误报
    react_samples: int = 8           # 预判采几个样。见 core/predict.py
    blink_distance: float = 70.0     # 每一次闪，落在离敌人多远的地方
    flash_seconds: float = 0.14      # 每一次闪现持续多久（暗角 + 减速跟着它走）
    slow_factor: float = 0.22        # 闪现那一下把游戏速度压到几倍
    slash_seconds: float = 2.0       # 这一套连招一共持续几秒
    blink_interval: float = 0.4      # 隔多久闪一下、砍一刀
    slash_damage: float = 45.0       # 砍一刀掉多少血。**一刀一结算**，不是每秒
    slash_reach: float = 110.0       # 挥砍弧光画多大。要 >= blink_distance，
                                     # 不然画出来的弧盖不住真会挨砍的那个位置
    exit_speed: float = 300.0        # 正常收招之后，朝敌人反方向离开的速度

    def ready(self, ball: Ball, match: Match) -> bool:
        """冷却好了也先憋着，等预判说自己快撞上了才放。"""
        return will_be_hit(match, ball, self.react_seconds, self.react_samples)

    def active(self, ball: Ball) -> bool:
        return ball.blink is not None

    def activate(self, ball: Ball, match: Match) -> None:
        target = match.opponent(ball)
        if target is None:
            return
        match.start_blink(
            ball, target,
            distance=self.blink_distance,
            flash_seconds=self.flash_seconds,
            slow_factor=self.slow_factor,
            slash_seconds=self.slash_seconds,
            blink_interval=self.blink_interval,
            reach=self.slash_reach,
            slash_damage=self.slash_damage,
            exit_speed=self.exit_speed,
        )


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

    def ready(self, ball: Ball, match: Match) -> bool:
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

    def ready(self, ball: Ball, match: Match) -> bool:
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
class GoSkill(Skill):
    """棋盘：把战场划成方格，每隔一段时间在空格里落一颗子——先黑后白。

    和刀、锤子同属**常驻被动**（ready 钉死成 False，起点是 on_spawn，不占技能
    条），但它是这几样里唯一**自己按时间动**的：刀和锤子只在自己被推进的时候
    转，撞不撞得上是对方的事；而这一样不需要任何触发，钟一到就落子。所以它是
    全场唯一一个"不看场上发生了什么、只因为时间到了就改变场地"的东西。

    落子的规则（用户定的）：

    - 黑子随机落在任意一个空格上，随后**四颗白子一颗接一颗地跟上**，落在它的
      上下左右四格上。
    - 两份间隔：白子之间隔 white_interval（很短，看着就是唰唰唰唰铺开的一圈），
      四颗落完之后才隔 interval 这个冷却起下一手。
    - 四邻里已经有子的那几格不进队列，白子就相应地少几颗，一颗都排不上就是
      "这一手不下白子"——所以棋盘越满，白子越少，黑子（伤害高的那种）占比越高。
    - 黑白都炸：踩上去掉血 **+ 减速**，减速不叠加。**黑子掉血更多。**

    踩上去的子**就没了**（用户定的"踩过就消失"）。所以棋子是地雷不是墙，棋盘
    一直是半空的、望得不停地补——这正是它和激光、蛛丝、毒刺那三个"永久不封顶"
    的被动最大的不同：那三样是**越积越多**，这一样是**一直在流**。它给对手的
    压力不来自"攒了多少"，来自落子的节奏。

    自己的子不炸自己（同激光、蛛丝、毒刺），踩上去也不会消耗——子只对对手
    有效。

    **棋盘本身不在这里**：它是 Match 的（见 Match.go_board），因为它是"战场
    被划成什么样"，属于场地。填在球上的是**节奏**（Ball.go_plan），两个望对打
    时共用一块棋盘、各走各的钟。
    """

    interval: float = 4.0           # 一手落完之后隔几秒起下一手（冷却）。
                                    # **这个数决定对手的压力**：越短，棋盘上同时
                                    # 存在的子越多
    white_interval: float = 0.2     # 同一手里白子之间隔几秒。就是"唰唰唰唰"那四下
                                    # 有多快，改它只改白子铺开的手感，不改节奏
    black_damage: float = 60.0      # 踩到黑子掉多少血
    white_damage: float = 25.0      # 踩到白子掉多少血。比黑子轻——白子是配菜，
                                    # 它的作用是把黑子周围那片格子也变成雷区
    slow_seconds: float = 2.0       # 踩到之后慢多久（黑白一样）
    slow_ratio: float = 0.45        # 慢多少，0.45 就是速度打五五折。

    def ready(self, ball: Ball, match: Match) -> bool:
        return False

    def activate(self, ball: Ball, match: Match) -> None:
        """常驻被动没有"放"这个动作。真的被调到了说明哪里写错了。"""
        raise NotImplementedError("棋盘是被动技能，不该被 activate")

    def on_spawn(self, ball: Ball, match: Match) -> None:
        """出生时把落子节奏挂在球上。

        **棋盘不在这里铺**：那是 Match 的事（见 Match.sync_go_board）——棋盘是
        "战场被划成什么样"，格子边长要从战场边长算出来，球不知道战场在哪。
        而且铺棋盘得等**两个玩家都选完**才算数（只有一个人有望才该有棋盘），
        出生这一个是早的。
        """
        ball.start_go(
            interval=self.interval,
            white_interval=self.white_interval,
            black_damage=self.black_damage,
            white_damage=self.white_damage,
            slow_seconds=self.slow_seconds,
            slow_ratio=self.slow_ratio,
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


@dataclass(frozen=True)
class KingSkill(Skill):
    """召唤骑士：从自己身上朝几个方向甩出一批骑士，之后就交给它们自己飞。

    这是一次性技能（duration = 0）：放出来这一瞬间骑士就已经在路上了，之后
    技能本身什么都不管——骑士不是"技能的效果"，是一颗**独立的球**，有自己的
    血量、自己的动量，活得比这一下长得多，也**不会因为冷却好了就消失**。
    所以这个技能真正调的是"多久能再造一批"，不是"骑士能撑多久"。

    **骑士只有被打死才消失**（用户定的），没有存活时长。也就是说场上骑士的
    数量 = 召唤批数 × count − 被打死的那些，活得越久堆得越多。所以 cooldown
    是这个角色唯一能调的**数量**旋钮：把它调短，骑士会一直累加。

    方向基准取国王自己的朝向（见 Match.summon_knights），不写死角度。
    """

    # 召出来的是什么。数值（血量、半径、撞人伤害）全在它身上，不在这里——
    # 骑士是一个完整的角色，不该被拆成散装参数塞进技能里。
    # 类型上允许 None 只是为了让 dataclass 的字段顺序成立（基类的 name/cooldown
    # 是必填的），真正的必填由 __post_init__ 兜底：漏配了在**开局读 roster 的时候**
    # 就当场报出来，不会拖到对局打了一半才发现
    knight: Character | None = None
    count: int = 3              # 一次召几个。均匀撒开，360°/count 一个方向
    launch_speed: float = 320.0  # 甩出去的初速度（像素/秒）。压在出生速度那一档里
                                 # （220~380），**不比出生速度快多少**——三个骑士一起
                                 # 冲脸太像一发爆发，慢一点才是"围上来"

    def __post_init__(self) -> None:
        if self.knight is None:
            raise ValueError("KingSkill 必须带上要召唤的骑士（见 config/roster.py）")

    def activate(self, ball: Ball, match: Match) -> None:
        match.summon_knights(
            owner=ball,
            knight=self.knight,
            count=self.count,
            launch_speed=self.launch_speed,
        )
