"""小球实体。

职责边界：只管自己——计时器、位移、血量、技能留在自己身上的状态。
撞墙由 Arena 裁定，撞球与伤害结算由 Match 裁定。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import pygame
from pygame.math import Vector2

from ..states.blade import Blade
from ..characters import Character
from ..states.blink import BlinkStrike
from ..states.go_board import GoPlan
from ..states.hammer import Hammer
from ..states.hook import Hook
from ..states.laser import Beam, LaserField
from ..states.thrust import Thrust
from ..states.venom import PoisonStack, Spike
from ..states.web import WebAnchor
from ..config.settings import (
    BALL_SPEED_MAX,
    BALL_SPEED_MIN,
    COLOR_AURA_FILL,
    COLOR_AURA_RING,
    COLOR_DEBUG_BOX,
    COLOR_DEBUG_VECTOR,
    COLOR_SLOW_RING,
    COLOR_VENOM_RING,
    PLAYER_COLORS,
    SLOW_RING_PADDING,
    THRUST_MIN_EXIT_SPEED,
    VENOM_STACK_RING_MAX,
    VENOM_STACK_RING_PADDING,
)


def random_velocity() -> Vector2:
    """随机方向 + 随机大小，得到一个初始动量。"""
    angle = random.uniform(0.0, math.tau)
    speed = random.uniform(BALL_SPEED_MIN, BALL_SPEED_MAX)
    return Vector2(math.cos(angle), math.sin(angle)) * speed


@dataclass
class Aura:
    """技能留在自己身上的范围光环（当前只有吸血鬼的蝙蝠圈用）。

    圈是跟着自己走的，所以只需要记住参数，圆心永远是自己。

    **没有自己的倒计时**——圈活多久由球上的 skill_active_remaining 说了算。
    两处各记一份计时的话，"球说技能结束了、圈说还没"这种不一致迟早会出现，
    而且冷却该从哪一刻开始算也会跟着含糊。统一到球上就只有一处真相。
    """

    radius: float
    slow_ratio: float          # 圈内敌人减速比例，0.5 就是速度砍半
    drain_per_second: float    # 每秒从圈内敌人身上吸走多少血


@dataclass
class TimedSlow:
    """踩到减速：**带时长**的减速，和光环那种"本帧有效"的不是一回事。

    光环和蛛丝都是"每帧重新申报"的：离开圈、离开线的下一帧就恢复，因为它们
    是**场地上的位置**决定的，人走了效果自然就没了（见 Match.begin_frame 那一套）。

    这一条不一样：它来自"踩了一下"这个**已经发生过的事件**，人跑开了也该继续慢
    一会儿。所以它必须自己带倒计时，不能被每帧的 reset_speed_scale 抹掉——
    抹掉的话踩上去只有一帧有效，等于没有。

    ratio 跟着这一份走，不在球上记一个总数：踩的时候扣多少，这一份就一直是多少，
    中途改配置不会回头改已经踩上的那一下（和 PoisonStack 同一个道理）。
    """

    remaining: float
    ratio: float


@dataclass
class Ball:
    """一个作战单位。

    尺寸来自角色（character.radius），颜色来自玩家队色（PLAYER_COLORS[player]），
    所以两位玩家选同一个角色也能分清。

    真正用来位移、撞墙、碰撞的那份速度是 effective_velocity，它由三样东西合成：

    - velocity      基础速度，"没有任何加成时"的样子，也是撞墙和弹性碰撞改的那个
    - boost_bonus   永久加速累计加出来的**绝对速度**（像素/秒），沿当前朝向加上去
    - speed_scale   被别人减速的临时折扣，每帧由 Match 重算，默认 1.0

    加速记成绝对值而不是倍率，是因为要"每档加一个固定值、跟当前速度无关"：倍率会
    随当前速度水涨船高，被撞慢之后加的也变少。改成绝对值后就恒定加
    spawn_speed × 技能的每档比例，不管当时是快是慢。

    但绝对值不能直接加进 velocity——那等于把加成焊死在基础速度里，吸住期间速度被
    合体速度整个覆盖时它会连同原速度一起丢掉。所以它单独存在 boost_bonus 里，
    用的时候现加。

    都是像素/秒口径，推进时必须乘 dt。
    """

    player: int
    character: Character
    position: Vector2
    velocity: Vector2             # 基础速度（不含任何加成）
    hp: float
    spawn_speed: float = 0.0      # 出生速度的大小。加速每档加它的固定比例，是"标尺"
    boost_stacks: int = 0         # 永久加速攒了几档
    boost_bonus: float = 0.0      # 加速累计加出来的绝对速度（像素/秒）
    cooldown_timer: float = 0.0   # 剩余冷却（秒）。**技能生效结束之后**才开始走
    skill_active_remaining: float = 0.0  # 技能生效还剩几秒（0 = 没有技能在生效）
    skill_active_total: float = 0.0      # 这次生效一共几秒，画进度条用
    silenced: bool = False        # 技能被封印中。只是一条开关，不带时长
    speed_scale: float = 1.0      # 被减速的折扣，每帧由 Match 重置
    aura: Aura | None = None      # 自己身上挂着的范围光环
    hook: Hook | None = None      # 自己甩出去的钩锁（在飞 or 正在往回拖人）
    # 自己画在墙上的激光。和 hook 不同，它**不是技能生效的标记**——激光是
    # 被动的，线画出来之后技能早就"结束"了（压根没有冷却这回事），这个字段
    # 只是"我留下了什么"的账本。没撞过墙就是 None
    lasers: LaserField | None = None
    # 绕着自己转的那把刀（武士的常驻被动）。同样是"我身上挂着什么"的账本，
    # 不是技能生效的标记：它没有冷却也没有生效时长，出生起就在转
    blade: Blade | None = None
    # 绕着自己抡的那把锤子（大锤的被动）。和 blade 同类：账本，不是"技能生效中"。
    # 和刀分开两个字段而不是合成一个"绕身武器"，是因为命中之后干的事完全不同
    # （刀蹭血、锤子打飞），合成一个就得在里面到处判是哪种
    hammer: Hammer | None = None
    # 正在冲的那一下穿刺。这个**是**"技能生效中"的标记（和 hook 同类）：
    # 冲刺的这几帧球不按自己的动量走，位置由 Match.update_thrusts 摆
    thrust: Thrust | None = None
    # 正在进行的闪现突袭（幻影刺客）。和 thrust 同类，**是**"技能生效中"的
    # 标记：不为空的时候技能不结束、冷却不走
    blink: BlinkStrike | None = None
    # 自己钉在墙上的那些蛛丝锚点（蜘蛛的被动）。和 lasers 同类，是"我留下了
    # 什么"的账本。每一根的另一头都连着**现在的自己**，所以这里只存墙上那点
    webs: list[WebAnchor] | None = None
    # 自己钉在墙上的那些毒刺（毒刺的被动）。和 webs 同类，也是"我留下了什么"
    # 的账本。区别是它扎完一次要重新蓄力，所以那些刺是**活的**（可变），
    # 而 WebAnchor 是 frozen 的
    spikes: list[Spike] | None = None
    # 自己**身上**叠着的中毒。这一条和上面那些账本都不一样：它不是"我留下了
    # 什么"，是"我中了什么"——和 silence 同类，是挂在球上的减益。谁中的毒就
    # 记在谁头上，跟下毒的人再无关系（那人死了毒照样走完）
    venom: list[PoisonStack] | None = None
    # 自己身上挂着的带时长的减速（踩到棋子）。和 aura 同类，是"我身上有什么"，
    # 不是"我留下了什么"——但它不看位置，只看时间，所以得自己带倒计时
    slow: TimedSlow | None = None
    # 望的落子节奏（棋盘钟 + 落出来的子是什么成色）。和 blade / hammer 同类：
    # 常驻的东西，出生时装上，之后一直在。**子不在球上**——棋盘是 Match 的
    # （见 Match.go_board），这里只有"多久落一手"
    go_plan: GoPlan | None = None
    # 当前朝向（单位向量）。速度被清零时还得靠它决定加速那一截往哪走
    heading: Vector2 = field(default_factory=lambda: Vector2(1.0, 0.0))

    def __post_init__(self) -> None:
        # 从 velocity 反推，这样直接构造 Ball 的场合（测试、以后的读档）
        # 也不用调用方记得把这两个填上
        if self.spawn_speed <= 0:
            self.spawn_speed = self.velocity.length()
        speed = self.velocity.length()
        if speed > 1e-9:
            self.heading = self.velocity / speed

    @classmethod
    def spawn(cls, player: int, character: Character, position: Vector2,
              velocity: Vector2 | None = None) -> "Ball":
        """满血、无冷却地生成一个球。"""
        return cls(
            player=player,
            character=character,
            position=position,
            velocity=random_velocity() if velocity is None else velocity,
            hp=character.max_hp,
        )

    # ---------------- 只读属性 ----------------
    @property
    def radius(self) -> int:
        return self.character.radius

    @property
    def color(self) -> tuple[int, int, int]:
        return PLAYER_COLORS[self.player]

    @property
    def center(self) -> tuple[int, int]:
        """取整后的圆心，供 pygame 绘制接口使用。"""
        return round(self.position.x), round(self.position.y)

    def center_at(self, offset: Vector2) -> tuple[int, int]:
        """加上镜头抖动之后的圆心。绘制走这个，物理永远用不加偏移的 position。"""
        return round(self.position.x + offset.x), round(self.position.y + offset.y)

    @property
    def boosted(self) -> bool:
        return self.boost_stacks > 0

    @property
    def effective_velocity(self) -> Vector2:
        """实际用来位移、用来撞墙、用来和别的球做碰撞的那个速度。

        加速那一截是**加在速度大小上**的（方向沿用当前朝向），不是乘一个倍率，
        所以每档加的绝对值和当时的速度无关。

        **定在原地的人此刻的动量是零**。甩着钩锁的渔夫就是这样：velocity 里
        存的那份是"松手之后接着飞的那份"，不是"现在有多快"——现在他根本没在动。
        所有问"现在"的地方都得按 0 算：锤头砸上来时没有渔夫自己的速度垫底（不然
        等于他一边站着一边还在往锤子上撞），刺客闪到他身后接过的也是 0（不然会
        凭空继承一份他不曾有的动量）。那份暂存的速度只在一个地方作数：收招推
        那一下之后的飞行。
        """
        if self.frozen:
            return Vector2(0.0, 0.0)
        speed = self.velocity.length()
        if speed > 1e-9:
            # 顺手把朝向记下来。下一帧速度要是被清零了（正面对撞的极端情况），
            # 加速那一截还得靠它决定往哪走。
            self.heading = self.velocity / speed
        return self.heading * (speed + self.boost_bonus) * self.speed_scale

    @property
    def speed(self) -> float:
        """当前移速（含加速与减速）。伤害按这个算，所以加速期间撞人更疼。"""
        return self.effective_velocity.length()

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def hp_ratio(self) -> float:
        """血量百分比，0~1。血条、按百分比换血都用它。

        用百分比而不是绝对值，是因为两个角色的 max_hp 不保证一样大：直接对调
        数值会让拿到的那份超过上限（血条爆表），或者换过来反而比原来少。
        """
        maximum = self.character.max_hp
        return self.hp / maximum if maximum > 0 else 0.0

    @property
    def missing_hp(self) -> float:
        """已损血量。死灵法师的撞击伤害按这个算——打得越狠越疼。"""
        return max(0.0, self.character.max_hp - self.hp)

    @property
    def frozen(self) -> bool:
        """定在原地不动。

        放钩锁期间就是这样：钩锁在飞的时候人不能跑，往回拖人的时候更不能跑。
        除了不走动量，这还意味着**霸体**——别人撞上来只会被弹回，推不动他。
        """
        return self.hook is not None

    @property
    def venom_stacks(self) -> int:
        """身上叠着几层毒。

        **层数就是列表长度**，不另记一个计数：两处各记一份的话，"毒掉完了但
        计数还留着"这种不一致迟早出现，而技能2 的伤害完全由这个数决定——
        报错一层就是一整下的偏差。
        """
        return 0 if self.venom is None else len(self.venom)

    @property
    def skill_active(self) -> bool:
        """技能正在生效中。

        问技能自己，而不是直接看倒计时：绝大多数技能确实按倒计时，但钩锁那种
        "到钩中人为止"的没有预定长度，只能由挂着的状态回答。见 Skill.active。
        """
        return self.character.skill.active(self)

    def skill_ready(self, match) -> bool:
        """能不能放技能。四道关，缺一不可：

        - 冷却走完了
        - 手上没有技能正在生效（持续型技能生效期间不该再放一次，否则每帧都会
          刷新，圈的剩余时间永远停在满格）
        - 没被沉默（见 Ball.silence。封它的可以是吸住，也可以是别的东西）
        - 技能自己没说不行

        这里**不看**是否已在加速中：加速是永久的、瞬时的，放完就没有"生效中"
        这个阶段，拿它当挡箭牌会让第二次永远放不出来。

        要 match 是为了那些"看场上局势才决定放不放"的技能：幻影刺客的技能是
        被动等触发的，它要拿整局去预判"我是不是快撞上了"（见 core/predict）。
        """
        return (
            self.cooldown_timer <= 0
            and not self.skill_active
            and not self.silenced
            and self.character.skill.ready(self, match)
        )

    # ---------------- 推进 ----------------
    def update(self, dt: float) -> None:
        """推进一帧：先走计时器，再按当前动量位移。"""
        self.tick(dt)
        self.position += self.effective_velocity * dt

    def tick(self, dt: float) -> None:
        """只走计时器，不动物理。加成到期不需要做任何还原动作。

        两个计时器各走各的：技能生效时长**照常走**——被沉默只是不能把技能
        **放出来**，已经在生效的技能不会被掐断，它该结束的时候照样结束；
        冷却则是在生效结束的那一刻才被点着（见 finish_skill），所以这里只是在
        给一段已经开始的冷却倒数。

        沉默不在这里，因为它**没有时长**：解不解封是施加方的事，见 Ball.silence。
        """
        if self.cooldown_timer > 0:
            self.cooldown_timer = max(0.0, self.cooldown_timer - dt)
        if self.skill_active_remaining > 0:
            self.skill_active_remaining = max(0.0, self.skill_active_remaining - dt)
            if self.skill_active_remaining <= 0.0:
                self.finish_skill()

    def reset_speed_scale(self) -> None:
        """把减速折扣抹回 1.0。Match 每帧开头调一次。

        必须每帧重置而不是"减速时设、离开时还原"：减速源可能中途消失
        （放减速的人被打死、圈到期），漏掉任何一条还原路径，这个折扣就会
        永久留在球上，越叠越慢最后停住。
        """
        self.speed_scale = 1.0

    def activate_skill(self, match) -> bool:
        """释放技能。冷却没好、正在生效、被沉默，都放不出来。

        效果由技能自己决定（写到球上的某个状态里），球这边只负责计时：

        - 一次性技能（duration = 0，比如加速）：效果当场结算完，立刻进冷却
        - 持续型技能（duration > 0，比如蝙蝠圈）：先走生效时长，**这段时间不计
          冷却**，等它结束了冷却才从零开始。所以"冷却 15 秒 + 持续 5 秒"的技能
          两轮之间实际隔 20 秒，而条上先黄后蓝、刚好接得上
        """
        if not self.skill_ready(match):
            return False
        skill = self.character.skill
        skill.activate(self, match)
        if skill.duration > 0.0:
            self.skill_active_remaining = skill.duration
            self.skill_active_total = skill.duration
        # 按倒计时生效的，上面那行已经让它 active() 为真了；按别的方式生效的
        # （钩锁看的是 ball.hook），由技能自己的 active() 说了算。
        # 两边都为假 = 这是一次性技能，效果当场结算完，立刻进冷却
        if not skill.active(self):
            self.cooldown_timer = skill.cooldown
        return True

    def finish_skill(self) -> None:
        """技能生效结束：收掉它留下的持续效果，冷却从这一刻开始算。

        清 aura / hook / blink 都是无条件的，因为一个球只有一个技能槽——场上
        不可能存在"这个球带着别人给的圈"的情况。哪天有了第二个能留持续效果的
        技能，这里要改成按技能各自清理。

        按倒计时的技能由 tick() 在倒计时归零时自动调到这里；不按倒计时的
        （钩锁）由 Match 在它该结束的那一刻调。
        """
        self.skill_active_remaining = 0.0
        self.skill_active_total = 0.0
        self.aura = None
        self.hook = None
        self.blink = None
        self.cooldown_timer = self.character.skill.cooldown

    # ---------------- 技能留在自己身上的状态 ----------------
    def add_boost(self, spawn_speed_gain: float) -> None:
        """永久加速攒一档：沿当前朝向，加"出生速度 × spawn_speed_gain"。

        spawn_speed_gain 由技能给出（0.5 就是半条出生速度）。加的是绝对值，
        所以每档涨得一样多，是线性叠加而不是越滚越快。
        """
        self.boost_bonus += spawn_speed_gain * self.spawn_speed
        self.boost_stacks += 1

    def start_aura(self, radius: float, slow_ratio: float,
                   drain_per_second: float) -> None:
        """挂上一个范围光环。重复释放就是刷新，不叠加。

        这里不接收持续时长：圈活多久由 activate_skill 记在 skill_active_remaining 上。
        """
        self.aura = Aura(
            radius=radius,
            slow_ratio=slow_ratio,
            drain_per_second=drain_per_second,
        )

    def cast_hook(self, hook_speed: float, pull_speed: float,
                  drain_per_second: float, reel_gap: float) -> None:
        """朝当前朝向甩出一条钩锁，出膛点在自己身前一个半径处。

        往后的推进（飞、弹墙、钩中、收线）全在 Match 里，这里只负责把这一发
        顺着朝向丢出去。朝向沿用 heading——"向原方向释放"，
        哪怕速度已经被撞成 0（只剩加速那一截）也照样有方向。
        """
        muzzle = self.position + self.heading * self.radius
        self.hook = Hook(
            position=Vector2(muzzle),
            velocity=self.heading * hook_speed,
            path=[Vector2(muzzle)],
            pull_speed=pull_speed,
            drain_per_second=drain_per_second,
            reel_gap=reel_gap,
        )

    def start_blade(self, angular_speed: float, inner_radius: float,
                    outer_radius: float, damage: float) -> None:
        """挂上一把绕身刀，从当前朝向那个角度开始转。

        起始角度取 heading 而不是写死 0：写死的话每个武士的刀都从"指向右"
        起步，同一局里双方看起来像同步的机械。跟着自己的朝向走，一眼能看出
        刀是长在球上的。
        """
        self.blade = Blade(
            angle=math.atan2(self.heading.y, self.heading.x),
            angular_speed=angular_speed,
            inner_radius=inner_radius,
            outer_radius=outer_radius,
            damage=damage,
        )

    def start_hammer(self, angular_speed: float, inner_radius: float,
                     outer_radius: float, head_radius: float,
                     damage_per_speed_sq: float) -> None:
        """挂上一把绕身锤，从当前朝向那个角度开始抡。

        起始角度和刀一样取 heading 而不是写死 0：同一局里两个大锤不该像同步
        的机械。锤头半径是**判定**用的（见 Hammer.hits），不是画多大。
        """
        self.hammer = Hammer(
            angle=math.atan2(self.heading.y, self.heading.x),
            angular_speed=angular_speed,
            inner_radius=inner_radius,
            outer_radius=outer_radius,
            head_radius=head_radius,
            damage_per_speed_sq=damage_per_speed_sq,
        )

    def start_go(self, interval: float, black_damage: float, white_damage: float,
                 slow_seconds: float, slow_ratio: float) -> None:
        """挂上落子的节奏（望的常驻被动）。

        和 start_blade / start_hammer 同类：出生时挂一次，之后它自己一直在。
        **棋盘不在这里**——棋盘是 Match 的（见 Match.go_board），那是"战场被划成
        什么样"，球不知道战场在哪。这里挂的只是"多久落一手、落出来是什么成色"。

        第一手的钟拧满（从 interval 开始倒数，而不是 0）：开局两颗球是随机撒在
        场上的，子也是随机落的，开局那一下两边撞上纯属白送。
        """
        self.go_plan = GoPlan(
            interval=interval,
            black_damage=black_damage,
            white_damage=white_damage,
            slow_seconds=slow_seconds,
            slow_ratio=slow_ratio,
            timer=interval,
        )

    def start_thrust(self, match, speed: float, distance: float,
                     damage: float) -> None:
        """朝敌人锁死一个方向冲出去。

        方向在**这一刻**定下来，之后不再改——敌人跑开了就打空，这是穿刺能被
        躲开的全部原因。这个方向也决定了冲完往哪走，所以它同时是"朝向"。

        冲完接着走的速度取的是当前实际速度（含加速、含减速折扣），也就是
        "如果没有这一下，它本来会以多快在跑"。出手前是静止的（或者刚被撞停）
        也要留一个下限，否则冲完就定在原地不动了。
        """
        direction = match.direction_to_opponent(self)
        # 冲完接着走的那份速度也锁在出手这一刻。冲刺期间球不走自己的动量，
        # 所以不先记下来的话，收招时就没得可恢复
        self.heading = direction
        self.thrust = Thrust(
            direction=direction,
            remaining=distance,
            speed=speed,
            damage=damage,
            exit_speed=max(self.speed, THRUST_MIN_EXIT_SPEED),
        )

    def record_wall_hit(self, point: Vector2, side: str,
                        damage_per_second: float) -> bool:
        """撞墙记一笔，推进激光的两种模式。返回是不是**新连出了一条线**。

        规则是"每两次撞到不同的墙上连一根线"，也就是一个开合：

        - 普通模式撞墙 → 进入**连线模式**，把这个墙面上的点攒下来
        - 连线模式撞**另一面**墙 → 两点连成一条激光，退回普通模式
        - 连线模式撞**同一面**墙 → 把攒着的点挪到新位置，仍是连线模式

        最后这条是"球贴着墙一路掠过去"的情形：掠墙会在同一面墙上留下很多个点，
        要是每一下都另起一个，攒着的那个点就会被一堆没用的点淹没，连出来的线也
        不知道从哪出发。挪过去之后，连出来的永远是"最新那一下"，好预测。

        攒的点存的是**墙面上的撞点**（Arena 报上来的那个垂足），不是球心——
        球心离墙还有一个半径，拿它连线的话激光的两头会在场子里面悬着。
        """
        grid = self.lasers
        if grid is None:
            self.lasers = grid = LaserField()

        if not grid.armed:
            grid.pending = Vector2(point)
            grid.pending_side = side
            return False

        if side == grid.pending_side:
            grid.pending.update(point)
            return False

        grid.beams.append(Beam(
            start=Vector2(grid.pending),
            end=Vector2(point),
            damage_per_second=damage_per_second,
        ))
        grid.pending = None
        grid.pending_side = ""
        return True

    def anchor_web(self, point: Vector2, damage_per_second: float,
                   slow_ratio: float) -> None:
        """在墙上钉一个锚点，从现在的位置拉出一根丝。

        和 record_wall_hit 是两种"撞墙留下东西"：那边要攒够两次才出一条线，
        这边撞一下就出一根，而且出的这根**立刻就能用**——不用等下一次撞墙。

        另一头**不记**：丝绷在锚点和"现在的自己"之间，球走到哪丝就从哪出发
        （见 Match.apply_webs）。所以刚钉下时这根丝只有一个半径那么长（锚点
        就在脚下那面墙上），球跑开之后才慢慢拉成一条横贯场地的长线。

        没有上限，也不会过期，和激光一个道理：这就是这个角色的成长曲线。
        """
        if self.webs is None:
            self.webs = []
        self.webs.append(WebAnchor(
            point=Vector2(point),
            damage_per_second=damage_per_second,
            slow_ratio=slow_ratio,
        ))

    def plant_spike(self, point: Vector2, side: str, size: float, damage: float,
                    poison_seconds: float, poison_per_second: float,
                    cooldown: float) -> None:
        """在墙上钉一根毒刺。

        数值全部**烤进这一根**（和 anchor_web 烤 damage/slow 同理）：以后调
        技能参数不会把墙上已有的旧刺一起改掉。side 是留着绘制用的——刺画成
        从墙面往场内扎的一根，得知道哪边是场内。

        没有上限，也不会过期，和激光、蛛丝一个道理：这就是这个角色的成长曲线。
        """
        if self.spikes is None:
            self.spikes = []
        self.spikes.append(Spike(
            point=Vector2(point),
            side=side,
            size=size,
            damage=damage,
            poison_seconds=poison_seconds,
            poison_per_second=poison_per_second,
            cooldown=cooldown,
        ))

    def poison(self, seconds: float, damage_per_second: float) -> None:
        """中毒：**加一层**，不是刷新。

        "加一层"和"刷新时长"是两种完全不同的叠法，这里选的是前者（用户定的
        "每层各走各的倒计时"）：连挨三下就是三个独立的沙漏错开着漏，谁先到点
        谁先掉。所以层数会自己慢慢褪下去，而不是"一直挂着一层、只是变长"。

        一条上限都没有：毒刺的伤害才是它的天花板，不是层数。真叠到十几层，
        按每层每秒的伤害算自然就疼得离谱了。
        """
        if self.venom is None:
            self.venom = []
        self.venom.append(PoisonStack(
            remaining=seconds,
            damage_per_second=damage_per_second,
        ))

    def apply_slow(self, seconds: float, ratio: float) -> None:
        """踩到减速：**不叠加**（用户定的）。

        已经在慢着的时候取**更狠的那一份**，不是两份乘起来——乘起来就是指数级
        地慢，连踩两颗几乎贴在原地（蛛丝的减速也是这么处理的，见 apply_webs：
        取最狠的一根，不相乘）。

        比例一样时把时长**取长的那个**，也就是"连踩两颗是重新计时，不是变成
        双倍时长"。比例比手上这份小的减速**整颗白踩**，连时长也不续：不然一颗
        轻的会把一颗重的顶掉，越踩越慢反倒变成越踩越快。

        写的是球上的状态，**每帧生效由 Match.apply_slows 负责**——这里只负责
        "记下来"，和 aura 那套分工一样。
        """
        current = self.slow
        if current is None:
            self.slow = TimedSlow(remaining=seconds, ratio=ratio)
            return
        if ratio < current.ratio:
            return
        if ratio == current.ratio:
            current.remaining = max(current.remaining, seconds)
            return
        self.slow = TimedSlow(remaining=seconds, ratio=ratio)

    def silence(self) -> None:
        """封住技能。这是一条**通用状态**，谁都能挂——吸住会挂它，以后别的技能
        （晕眩、禁魔、破防……）也可以挂它，球这边不关心是谁挂的。

        只管开关，**不管时长**：封多久是施加方的事，施加方自己负责解封。
        所以这里没有倒计时——未来的沉默未必是按时间解除的（"直到撞到墙为止"、
        "直到拉开距离为止"），那种沉默根本没法用一个秒数表达。带时长的沉默
        也应该把计时器放在施加方那边，到点了调 unsilence。

        封的是"开"这个动作，不是技能本身：冷却照常在后台走，生效中的技能也
        照常走完。所以解封的一方一松口就能接着放，不用从头等冷却。
        """
        self.silenced = True

    def unsilence(self) -> None:
        """解封。由施加方在它认为该结束的时刻调用。"""
        self.silenced = False

    def rebound(self, axis: str, sign: float) -> None:
        """把球在这个轴上的运动方向定成 sign 指的那一边（撞墙的镜面反射用）。

        方向和速度大小是分开存的：velocity 存"基础速度"，朝向另外记在 heading 上。
        所以两样都得改。只改 velocity 会漏掉一种球——加速攒得很大、基础速度已经被
        压成 0 的那种，它的 velocity 恒为 0，翻来翻去还是 0，方向其实全在 heading 上。
        漏掉这一步，那种球会顶着墙一路滑，再也飞不回场内，对局就永远打不完了。
        """
        if axis == "x":
            self.velocity.x = sign * abs(self.velocity.x)
            self.heading.x = sign * abs(self.heading.x)
        elif axis == "y":
            self.velocity.y = sign * abs(self.velocity.y)
            self.heading.y = sign * abs(self.heading.y)
        else:
            raise ValueError(f"未知的轴：{axis}")

    def set_effective_velocity(self, velocity: Vector2) -> None:
        """把"实际速度"写回去（反解：先除掉减速折扣，再减掉加速那一截）。

        碰撞这类会重写速度的场合一律走这里，别直接赋值 self.velocity——
        那会把这一整轮的加速直接抹掉。
        """
        scale = self.speed_scale
        target = velocity / scale if scale > 1e-9 else velocity
        speed = target.length()
        if speed > 1e-9:
            self.heading = target / speed
        # 加速那一截是永久的，撞不掉：撞完剩下的速度若比它还小，基础速度就归零，
        # 球仍然按加速那一截继续走，不会停在原地。
        self.velocity = self.heading * max(0.0, speed - self.boost_bonus)

    # ---------------- 血量 ----------------
    def take_damage(self, amount: float) -> None:
        self.hp = max(0.0, self.hp - amount)

    def heal(self, amount: float) -> float:
        """回血，上限是角色的满血值。返回**实际**回了多少（满血时是 0）。

        返回实际量是给特效用的：不满血的那一方吸血才该飘绿字，满血还飘绿字
        就是凭空多出来的假数字，看着像还在回血。
        """
        before = self.hp
        self.hp = min(self.character.max_hp, self.hp + amount)
        return self.hp - before

    # ---------------- 绘制 ----------------
    # offset 是镜头抖动的位移，只有绘制吃它。物理永远用不加偏移的 position，
    # 所以震动纯粹是视觉效果，不会把球推进墙里。
    def draw_aura(self, surface: pygame.Surface, offset: Vector2) -> None:
        """画范围光环。要在球之前画，免得盖住球。"""
        if self.aura is None:
            return
        radius = round(self.aura.radius)
        if radius <= 0:
            return

        center = self.center_at(offset)
        # 半透明填充靠一张带 alpha 的临时画布，pygame 的 draw.circle 不支持 alpha
        fill = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(fill, (*COLOR_AURA_FILL, 70), (radius, radius), radius)
        surface.blit(fill, (center[0] - radius, center[1] - radius))
        pygame.draw.circle(surface, COLOR_AURA_RING, center, radius, width=2)

    def draw_venom(self, surface: pygame.Surface, offset: Vector2) -> None:
        """画中毒：球外面套一圈毒绿，**层数越多越粗**。

        和光环一样画在球**之前**——这圈是贴在球面上的，盖上去会像球变胖了。
        粗细封顶在 VENOM_STACK_RING_MAX 层：再往上叠圈会一直长，叠到十几层
        时那圈能糊掉半个战场，而"很毒"这件事到这个粗细已经说清楚了。
        """
        stacks = self.venom_stacks
        if stacks <= 0:
            return
        center = self.center_at(offset)
        radius = self.radius + VENOM_STACK_RING_PADDING
        width = max(2, min(stacks, VENOM_STACK_RING_MAX))
        pygame.draw.circle(surface, COLOR_VENOM_RING, center, radius, width)

    def draw_slow(self, surface: pygame.Surface, offset: Vector2) -> None:
        """画减速：球外面套一圈冷蓝。

        比中毒那圈（半径 + 5）再往外一点（半径 + 11），两圈能同时看见——一颗球
        完全可能既中着毒又被棋子炸慢。和中毒一样画在球**之前**，它是套在球面上
        的，盖上去像球变胖了。

        没有"层数"这回事（减速不叠加），所以这圈的粗细是固定的，只报个"在慢着"。
        还剩多久画不出来，那是技能条上的事（见 app.go_display）。
        """
        if self.slow is None:
            return
        center = self.center_at(offset)
        pygame.draw.circle(
            surface, COLOR_SLOW_RING, center, self.radius + SLOW_RING_PADDING, 2
        )

    def draw(self, surface: pygame.Surface, offset: Vector2) -> None:
        center = self.center_at(offset)
        pygame.draw.circle(surface, self.color, center, self.radius)
        # 内圈高光，让球体看起来更有体积感；加速时换成亮白，一眼能看出谁在加速
        highlight = (255, 255, 255) if self.boosted else tuple(
            min(255, c + 60) for c in self.color
        )
        pygame.draw.circle(
            surface, highlight, center, self.radius, width=max(2, self.radius // 6)
        )

    def draw_debug(self, surface: pygame.Surface, font: pygame.font.Font,
                   vector_scale: float, offset: Vector2) -> None:
        """画出碰撞箱与当前动量。"""
        radius = self.radius
        center = self.center_at(offset)

        # 碰撞箱：圆的外接正方形
        box = pygame.Rect(0, 0, radius * 2, radius * 2)
        box.center = center
        pygame.draw.rect(surface, COLOR_DEBUG_BOX, box, width=1)
        pygame.draw.circle(surface, COLOR_DEBUG_BOX, center, 2)

        # 动量矢量（按 vector_scale 缩短，否则 380px/s 的箭头比战场还长）。
        # 画的是实际速度，所以加速期间箭头会明显变长。
        velocity = self.effective_velocity
        speed = velocity.length()
        if speed > 1e-6:
            tip = self.position + offset + velocity * vector_scale
            tip_point = (round(tip.x), round(tip.y))
            pygame.draw.line(surface, COLOR_DEBUG_VECTOR, center, tip_point, 2)

            back = velocity / speed * 8
            for angle in (150, -150):
                point = tip + back.rotate(angle)
                pygame.draw.line(surface, COLOR_DEBUG_VECTOR, tip_point,
                                 (round(point.x), round(point.y)), 2)

        label = (
            f"P{self.player + 1} hp={self.hp:.0f} "
            f"v=({velocity.x:.0f},{velocity.y:.0f}) |v|={speed:.0f}"
        )
        surface.blit(
            font.render(label, True, COLOR_DEBUG_VECTOR),
            (center[0] + radius + 6, center[1] - 8),
        )
