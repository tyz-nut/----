"""一局对战的规则与状态。

把"规则"从 app 里抽出来：谁在场上、血量、技能释放、碰撞结算、胜负。
app 只负责界面与主循环，不参与任何判定。

碰撞效果本身不在这里——那是角色的职责（characters/）。Match 只负责
"什么时候问角色"和"拿到主张之后怎么执行"。
"""

from __future__ import annotations

from dataclasses import dataclass

from pygame.math import Vector2

from .arena import Arena
from .ball import Ball
from .characters import Character, CollisionOutcome
from .effects import Effects
from .hook import Hook, point_from_end, polyline_length
from .config import (
    BALL_SPAWN_MIN_GAP,
    COLOR_HOOK,
    HOOK_RELEASE_SPEED,
    LATCH_RELEASE_SPEED,
    PLAYER_NAMES,
    SEPARATION_EPSILON,
)


@dataclass
class Latch:
    """一对被绑在一起做连体位移的球。

    "连体位移"是个**通用机制**，不属于吸血鬼：谁想让两球粘成一团走，调
    Match.start_latch 就行（角色可以在碰撞主张里要，技能也可以直接调）。
    吸血鬼只是当前唯一用它的人。

    绑住期间两球不再各飞各的，而是当一团整体平移，所以速度记在这里而不是各自的
    ball.velocity 上——那两份速度在吸住期间是失效的，松口时才按这份速度重新写回。

    velocity 存的是**实际速度**（含加速），因为合体飞行本来就是两球真正的运动，
    加速当然要算进去。早先这里存的是基础速度，结果是：吸住期间那一份加速被"挂起"
    了，球其实是按没加速的速度在飞；一松口加速又整个加回来，普通小球会凭空窜快
    一大截（实测攒 3 档时凭空多出 +463px/s，看着就像松口给它加了速）。

    存实际速度不怕"加速被焊进基础速度"——松口时走的是 ball.set_effective_velocity，
    它会按各自的加成分量正确地减回去（两只球的加速不一样也各算各的）。
    """

    grabber: int             # 抓人的一方（玩家序号）
    victim: int              # 被绑住的一方
    velocity: Vector2        # 合体飞行速度（基础速度，不含加速倍率）
    remaining: float         # 还剩几秒松口
    drain_per_second: float  # 每秒从 victim 身上吸走多少血
    silences: bool = False   # 这一对是不是同时封着对方的技能（松口时按它解封）


class Match:
    """一局对战。"""

    def __init__(self, arena: Arena, effects: Effects | None = None) -> None:
        self.arena = arena
        # 特效总线。Match 只往里喊"这里发生了什么"，不碰任何绘制代码；
        # 不传就是一个默认的（扣血数字用 pygame 默认字体）。app 会传一个带中文字体的进来
        self.effects = effects if effects is not None else Effects()
        self.balls: dict[int, Ball] = {}   # 玩家序号 -> 该玩家的球
        self.touching = False              # 上一帧两球是否已经贴在一起
        self.latch: Latch | None = None    # 当前粘在一起的两球
        self.finished = False
        self.winner: int | None = None     # finished=True 且 winner=None 表示平局

    # ---------------- 组装 ----------------
    def both_picked(self) -> bool:
        return all(player in self.balls for player in range(len(PLAYER_NAMES)))

    def pick(self, player: int, character: Character) -> None:
        """给某个玩家换上角色，在场上随机位置满血生成。"""
        self.balls[player] = self._spawn(player, character, self._others(player))
        self.reset_outcome()

    def restart(self) -> None:
        """保留已选角色，重新随机位置与动量；血量、技能、胜负全部复位。"""
        placed: list[Ball] = []
        rebuilt: dict[int, Ball] = {}
        for player in sorted(self.balls):
            ball = self._spawn(player, self.balls[player].character, placed)
            rebuilt[player] = ball
            placed.append(ball)
        self.balls = rebuilt
        self.reset_outcome()

    def reset_outcome(self) -> None:
        self.touching = False
        self.latch = None
        self.finished = False
        self.winner = None
        # 绑住被一笔勾销，挂在人身上的沉默、飞在半路的钩锁、画在墙上的激光
        # 也得跟着走，否则重开之后有一方会带着莫名其妙的封印、渔夫会定在原地
        # 动不了、上一局切出来的那些线还会继续割人
        for ball in self.balls.values():
            ball.unsilence()
            ball.hook = None
            ball.lasers = None
        self.effects.clear()

    def _others(self, player: int) -> list[Ball]:
        return [ball for index, ball in self.balls.items() if index != player]

    def _spawn(self, player: int, character: Character, others: list[Ball]) -> Ball:
        position = self.arena.random_spawn_point(
            character.radius, others, gap=BALL_SPAWN_MIN_GAP
        )
        return Ball.spawn(player, character, position)

    # ---------------- 推进 ----------------
    def update(self, dt: float) -> None:
        # 特效先推进，而且放在 finished 判断**之前**：分出胜负的那一下也得把
        # 圈炸完、把数字飘完，不能打死人的瞬间画面就定住了
        self.effects.update(dt)
        if self.finished:
            return

        # 减速是"本帧有效"的，所以每帧都先把折扣抹回 1.0，再由光环重新打上去。
        # 必须在这里无条件做，不能等 apply_auras 里去管：放光环的球可能中途死掉，
        # 那条还原路径就断了，折扣会永久留在对方身上，越叠越慢直到停住。
        for ball in self.balls.values():
            ball.reset_speed_scale()
        self.apply_auras(dt)
        # 激光和光环同一批结算：都是"场上的东西每帧对球做什么"，而且都不关心
        # 球这一刻在不在动。放在吸住/钩锁的提前返回之前，所以被吸住、被拖着的
        # 人也照样会被线打到——线是画在墙上的，跟谁在动没关系
        self.apply_lasers(dt)
        if self.finished:
            return

        if self.latch is not None:
            # 吸住期间两球当一团飞，但光环照常结算——这正是"圈子的吸血和吸住的
            # 吸血可以同时存在"的落点
            self.update_latch(dt)
            return

        # 钩锁先走：它这一帧可能钩中人，于是被钩的那位从这一帧起就改由折线决定位置
        self.update_hooks(dt)
        reeling = self.pulled_pair()
        victim = reeling[1] if reeling is not None else None
        if self.finished:
            # 钩锁把人拖死的：位置是折线刚摆上去的，可能还压在墙里。
            # 收尾前先把两颗球摆回场内再退出，别让尸体挂在那儿
            self.keep_inside(victim)
            return

        for ball in self.balls.values():
            # 甩钩锁的人定在原地，被钩回来的人由折线拖着走——两种都不按各自的动量
            # 位移。但计时器照走，否则技能冷却和生效时长会被钩锁冻住
            if ball.frozen or ball is victim:
                ball.tick(dt)
            else:
                ball.update(dt)

        self.cast_ready_skills()
        self.resolve_collision()
        if self.latch is not None:
            # 这一帧刚吸上。不能再走各自的撞墙判定——那会把粘住的一对拆开，
            # 但这一对的边界还是得守（见 correct_latch_walls）
            self.correct_latch_walls()
            return

        # 撞墙放在最后：球球分离可能把某颗球推进墙里，让墙来做最终裁决
        self.keep_inside(victim)

    def keep_inside(self, victim: Ball | None) -> None:
        """守边界：这一帧结束时，两颗球都必须整个待在战场里。

        放在所有位移之后（球球分离也算位移）：分离、收招推开、折线拖拽都可能
        把球顶到墙外。撞墙判定本身自带这一步，但**被钩锁控住的两球不走撞墙**
        ——一个定着不动、一个由折线摆位置——它们要是被顶到墙外就没人管了，
        渔夫更是会一直挂在那儿（冻结期间永远轮不到撞墙判定）。

        这两种球只**夹**位置、不反弹：它们的位置是"被摆"的，不是飞过去的，
        折一下会凭空给出一段镜像位移，速度箭头也会平白翻个向——而收招那一刻
        的速度是另有安排的。夹是连续的，被拖着走过墙角时球会贴着墙滑，不跳。

        分胜负那一帧也整条走这个分支：那一帧没有"反弹"可言了，只要别让球挂在
        墙里就行（钩锁可能正好把人拖到墙上拖死、或者有人死在墙边）。
        """
        for ball in self.balls.values():
            if ball.frozen or ball is victim or self.finished:
                self.arena.clamp_inside(ball.position, ball.radius)
                continue
            hit = self.arena.bounce_off_walls(ball)
            if hit is not None:
                self.effects.bounce(hit.point, ball.color, ball.speed)
                # 撞墙这件事光有几何还不够，被动技能（激光）要听这一声。
                # 主动技能走 cast_ready_skills，被动技能走这里
                ball.character.skill.on_wall_hit(ball, self, hit.point, hit.side)

    # ---------------- 钩锁 ----------------
    def update_hooks(self, dt: float) -> None:
        """推进场上所有钩锁：在飞的接着飞，在收线的接着拉。"""
        for ball in self.balls.values():
            hook = ball.hook
            if hook is None:
                continue
            if hook.reeling:
                self.reel_hook(ball, hook, dt)
            else:
                self.fly_hook(ball, hook, dt)
            if self.finished:
                return

    def fly_hook(self, owner: Ball, hook: Hook, dt: float) -> None:
        """钩锁在飞：走一步、可能弹墙、可能钩中人。

        折线的维护方式是"末端永远跟着钩尖走，撞墙时才把它钉死成拐角、另起一段"。

        拐角取的是**上一帧位置到越界位置这条线段与墙面的交点**，不是越界后的坐标：
        后者在墙外面（最多出去 speed×dt），收线时敌人会跟着在墙外走一截。
        折回场内之后的位置则是新一段的起点，两段在拐角处正好接上。
        """
        start = Vector2(hook.position)
        hook.position += hook.velocity * dt
        target = Vector2(hook.position)

        if self.arena.bounce_point(hook.position, hook.velocity):
            hook.path[-1] = self.arena.wall_crossing(start, target)   # 钉死这一段的拐角
            hook.path.append(Vector2(hook.position))                  # 折回场内，新一段
            self.effects.bounce(hook.path[-2], COLOR_HOOK, hook.velocity.length())
        else:
            hook.path[-1] = Vector2(hook.position)

        for other in self.balls.values():
            if other is owner or not other.alive:
                continue
            if (other.position - hook.position).length() > other.radius:
                continue
            self.hook_hit(owner, other, hook)
            return

    def hook_hit(self, owner: Ball, victim: Ball, hook: Hook) -> None:
        """钩中了：把对方拽到钩尖上，并把收线要走的折线准备好。"""
        hook.target = victim.player
        # 钩中时对方圆心离钩尖最多差一个半径，直接吸到钩尖上。这点位移看不出来，
        # 但能保证收线的起点严格落在折线上
        victim.position = Vector2(hook.position)
        hook.path[-1] = Vector2(hook.position)

        # 收线终点：渔夫身前，两球贴住再留一条缝。插在 path 开头，因为收线是
        # 从末端往回走的，终点得在路的最那头
        outward = hook.path[0] - owner.position
        length = outward.length()
        direction = outward / length if length > 1e-9 else owner.heading
        rest = owner.position + direction * (
            owner.radius + victim.radius + hook.reel_gap
        )
        hook.path.insert(0, rest)
        hook.total = polyline_length(hook.path)
        hook.pulled = 0.0

    def reel_hook(self, owner: Ball, hook: Hook, dt: float) -> None:
        """收线：对方沿钩锁当初走过的那条路被原路拖回来，一路持续掉血。"""
        victim = self.balls.get(hook.target)
        if victim is None or not victim.alive or not owner.alive:
            # 有人没了，钩锁随即作罢。走 finish_skill 收尾，好让冷却从这一刻开始
            owner.finish_skill()
            return

        before = Vector2(victim.position)
        hook.pulled = min(hook.total, hook.pulled + hook.pull_speed * dt)
        victim.position = point_from_end(hook.path, hook.pulled)

        # 速度是推出来的，不是自己演的：位移由折线定，velocity 只是让调试箭头
        # 和伤害口径跟得上，不至于指着一个方向却往另一个方向飞
        if hook.pulled > 0.0:
            victim.set_effective_velocity((victim.position - before) / dt)

        # 拖的过程中两人不算碰撞，但血照扣——扣的是"被钩住"这件事，不是撞出来的
        drained = hook.drain_per_second * dt
        victim.take_damage(drained)
        self.effects.drain_damage(victim.player, victim.position, drained)
        self.judge()
        if self.finished:
            return

        if hook.pulled >= hook.total:
            self.release_hook(owner, victim, hook)

    def release_hook(self, owner: Ball, victim: Ball, hook: Hook) -> None:
        """收线到位：两球沿连线相互推开，技能结束、渔夫解冻、开始进冷却。

        渔夫被定住期间攒下的那份动量不作数——他收招时的速度就是这一推给的，
        和松开吸住是同一套写法。
        """
        offset = victim.position - owner.position
        length = offset.length()
        normal = offset / length if length > 1e-9 else Vector2(1.0, 0.0)
        push = HOOK_RELEASE_SPEED / 2
        owner.set_effective_velocity(-normal * push)
        victim.set_effective_velocity(normal * push)

        owner.finish_skill()
        # 推完之后两人是分开的，复位接触标记；否则下一次真撞上会被当成"还贴着"漏掉
        self.touching = False

    def pulled_pair(self) -> tuple[Ball, Ball] | None:
        """当前正被钩锁往回拖的那一对（渔夫, 敌人），没有则为 None。"""
        for ball in self.balls.values():
            hook = ball.hook
            if hook is not None and hook.reeling:
                victim = self.balls.get(hook.target)
                if victim is not None:
                    return ball, victim
        return None

    def _is_pulled_pair(self, first: Ball, second: Ball) -> bool:
        pair = self.pulled_pair()
        return pair is not None and first in pair and second in pair

    def cast_ready_skills(self) -> None:
        """技能自动释放：冷却一好就放，玩家不需要操作。吸住期间不释放。"""
        for ball in self.balls.values():
            if ball.alive:
                ball.activate_skill(self)

    # ---------------- 范围光环 ----------------
    def apply_auras(self, dt: float) -> None:
        """结算范围光环：圈内的敌人被减速，并被持续吸取（吸出来的补给圈的主人）。

        判定用**圆心**是否落在圈内，和画出来的那个圈严格一致（不是"圆面相交"）。
        所以贴着圈边站还能吃到，圆心一出圈就立刻恢复——减速不残留。
        """
        for owner in self.balls.values():
            aura = owner.aura
            if aura is None or not owner.alive:
                continue
            for target in self.balls.values():
                if target is owner or not target.alive:
                    continue
                offset = target.position - owner.position
                if offset.length_squared() > aura.radius * aura.radius:
                    continue
                target.speed_scale = min(target.speed_scale, 1.0 - aura.slow_ratio)
                drained = aura.drain_per_second * dt
                target.take_damage(drained)
                self.effects.drain_damage(target.player, target.position, drained)
                # 回血要报**实际**回的量：圈的主人满血时这一下回的是 0，
                # 不该飘出绿字来
                healed = owner.heal(drained)
                if healed > 0.0:
                    self.effects.heal(owner.player, owner.position, healed)
        self.judge()

    # ---------------- 激光 ----------------
    def apply_lasers(self, dt: float) -> None:
        """结算墙上那些激光：压在线上的人持续掉血，**多根线叠加**。

        判定是"圆心到线段的距离 ≤ 对方半径"，也就是画出来的那条线真的挨上了
        球面才作数——两头都是墙面上的点，线本身贴在战场边上，用圆心判定的话
        贴墙走的人反而吃不到。

        自己的线不伤自己。掉血走 effects.drain_damage（红字、攒着报），和吸血
        是同一路数字，因为性质一样：都是每帧结算的持续伤害，一帧飘一个数字
        会糊成一片。
        """
        for owner in self.balls.values():
            grid = owner.lasers
            if grid is None or not grid.beams or not owner.alive:
                continue
            for target in self.balls.values():
                if target is owner or not target.alive:
                    continue
                # 多根叠加：压在几条线上就是几倍的每秒伤害
                rate = sum(
                    beam.damage_per_second
                    for beam in grid.beams
                    if beam.hits(target.position, target.radius)
                )
                if rate <= 0.0:
                    continue
                dealt = rate * dt
                target.take_damage(dealt)
                self.effects.drain_damage(target.player, target.position, dealt)
        self.judge()

    # ---------------- 碰撞 ----------------
    def resolve_collision(self) -> None:
        """两球相撞。发生什么由角色主张，Match 只负责执行。"""
        if len(self.balls) < 2:
            self.touching = False
            return

        first, second = (self.balls[player] for player in sorted(self.balls))
        offset = second.position - first.position
        minimum = first.radius + second.radius

        if offset.length_squared() >= minimum * minimum:
            self.touching = False
            return

        distance = offset.length()
        # 两球正好重合时法线无从谈起，随便挑一个方向把它们推开
        normal = offset / distance if distance > 0 else Vector2(1.0, 0.0)

        if self._is_pulled_pair(first, second):
            # 钩锁正把对方拖过来，这一路上两球不算碰撞——不然拖到身前那一瞬间
            # 会先互撞一下，白扣一次血。接触标记也一并复位，好在收线结束后
            # 重新开始算"刚贴上"
            self.touching = False
            return

        # 效果只在"刚贴上"的那一帧结算一次。没有这个标记的话，
        # 两球重叠期间每一帧都会再互扣一次血。
        if self.touching:
            self.separate(first, second, normal, distance, minimum)
            return
        self.touching = True

        # 先问双方各自的主张。必须在弹开之前问：撞击伤害读的是"撞上去那一瞬间"的速度
        first_wants = first.character.on_collision(first, second)
        second_wants = second.character.on_collision(second, first)

        # 撞击伤害只要撞上就结算。抓取只顶替"弹开"，不免除伤害——
        # 所以被抓住的一方在被抓住的那一瞬间仍然打得出这一下。
        second.take_damage(first_wants.damage_to_other)
        first.take_damage(second_wants.damage_to_other)
        self.effects.impact(
            first, second,
            first_takes=second_wants.damage_to_other,
            second_takes=first_wants.damage_to_other,
        )
        self.judge()
        if self.finished:
            # 有人被这一下打死了，弹开还是吸住都不必再谈
            self.separate(first, second, normal, distance, minimum)
            return

        # 抓取：不弹开，改成粘住持续吸取。排在霸体**前面**——霸体挡的是"被推动"，
        # 不是"被碰上"：抓取本身照常发生，只是抓到手之后两边都动不了
        # （见 combined_velocity：推不动的一方等效无穷大质量，合体速度由它说了算）
        if first_wants.grabs or second_wants.grabs:
            grabber, victim, wants = (
                (first, second, first_wants) if first_wants.grabs
                else (second, first, second_wants)
            )
            # 先摆到刚好相切，吸住期间就保持这个姿势。霸体的一方不让路，
            # 所以这一步的位移全由抓人的一方走完
            self.separate(first, second, normal, distance, minimum)
            self.start_latch(grabber, victim, wants.grab_seconds,
                             wants.grab_drain_per_second, silences=wants.silences)
            return

        # 霸体：定住的一方推不动，撞上来的一方原路弹回。
        # 走到这里说明没人想抓（谁都抓的话上面那条就返回了），所以这是
        # "普通撞击撞上霸体"的情形
        if first.frozen or second.frozen:
            self.reflect_off(first, second, normal, distance, minimum)
            return

        # 走到这里说明双方都不抓。此时 silences 一概不生效——沉默没有时长，
        # 必须有人负责解封，而"撞一下"这件事本身没有结束时刻，封了就没人解得开。
        # 所以从碰撞来的沉默只跟抓取配着用（绑多久就封多久）。想只封不绑，
        # 只能由技能来给：技能有生命周期，能在该结束的时候自己 unsilence。

        # 等质量弹性碰撞：沿法线的速度分量互换。
        # 先把两个速度取出来再写回，否则第二行算的是已经被改过的 first。
        first_velocity = first.effective_velocity
        second_velocity = second.effective_velocity
        first.set_effective_velocity(
            first_velocity - (first_velocity - second_velocity).dot(normal) * normal
        )
        second.set_effective_velocity(
            second_velocity - (second_velocity - first_velocity).dot(normal) * normal
        )

        self.separate(first, second, normal, distance, minimum)

    def reflect_off(self, first: Ball, second: Ball, normal: Vector2,
                    distance: float, minimum: float) -> None:
        """霸体反弹：定住的一方纹丝不动，撞上来的一方按镜面反射弹回去。

        反射的就是撞墙那一套（法线方向的速度分量翻个个儿，切向的留着），
        所以正面撞上来是"原路返回"，斜着撞是擦着弹开。伤害不在这里管——
        霸体只顶替"被推动"，两边该吃什么伤害照常在前面结算过了，
        和"抓取只顶替弹开、不免除伤害"是同一条原则。
        """
        frozen = first if first.frozen else second
        other = second if frozen is first else first
        if not other.frozen:        # 两边都是霸体（两个渔夫都甩着钩）就都别弹
            velocity = other.effective_velocity
            other.set_effective_velocity(velocity - 2.0 * velocity.dot(normal) * normal)
        self.separate(first, second, normal, distance, minimum)

    def separate(self, first: Ball, second: Ball, normal: Vector2,
                 distance: float, minimum: float) -> None:
        """把两球沿法线推到刚好相切（再多推一点点，见 config.SEPARATION_EPSILON）。

        霸体的一方不让路，所以那份位移全由对方一个人走完——否则会被推着挪窝，
        "定住"就废了。
        """
        push = (minimum - distance) / 2 + SEPARATION_EPSILON
        if first.frozen and second.frozen:
            return                  # 两边都是墙，谁也推不动谁，就这么叠着
        if first.frozen:
            second.position += normal * push * 2
        elif second.frozen:
            first.position -= normal * push * 2
        else:
            first.position -= normal * push
            second.position += normal * push

    # ---------------- 吸住 ----------------
    def start_latch(self, grabber: Ball, victim: Ball, seconds: float,
                    drain_per_second: float, silences: bool = False) -> None:
        """把两球绑成一团：从此一起飞，抓人的一方持续吸取。

        连体位移和沉默是两个独立开关，可以只要一个：

        - 只绑不封：silences=False
        - 只封不绑：别调这个，直接 victim.silence()

        收的是裸数值而不是 CollisionOutcome，这样技能也能直接用——
        以后一个"钩锁"技能（把对手拖过来绑住）就是这个签名。
        """
        self.latch = Latch(
            grabber=grabber.player,
            victim=victim.player,
            velocity=self.combined_velocity(grabber, victim),
            remaining=seconds,
            drain_per_second=drain_per_second,
            silences=silences,
        )
        if silences:
            # 封的是"开"这个动作（Ball.silence 只让 skill_ready 变假），所以
            # 已经被放出来的技能不会被打断——这正是"已经开了就不能打断"的落点
            victim.silence()

    @staticmethod
    def combined_velocity(first: Ball, second: Ball) -> Vector2:
        """动量守恒的合体速度：按质量加权（质量取截面积，也就是半径的平方）。

        半径相同时就是两速度的平均，所以正面对撞会当场停住、同向追赶会取中间值。

        用的是实际速度（含加速）——见 Latch 的说明。

        **霸体的一方是按无穷大质量算的**：推不动的东西，合体速度当然由它说了算，
        抓它的人那份动量全被它吃掉。渔夫甩着钩锁时自己是静止的，所以"吸住霸体"
        的结果就是两个人都停在原地——一个吸不动、一个推不动。注意这里取的是
        "定住"这个事实而不是它速度向量里的存量：定住的球速度字段里可能还留着
        放技能之前那一份，那份是不作数的（它已经不动了），照它算会让两边一起飘走。
        """
        if first.frozen or second.frozen:
            return Vector2()
        first_mass = first.radius ** 2
        second_mass = second.radius ** 2
        return (
            first.effective_velocity * first_mass
            + second.effective_velocity * second_mass
        ) / (first_mass + second_mass)

    def correct_latch_walls(self) -> None:
        """把粘住的一对当成一个刚体来守边界（见 Arena.bounce_rigid_pair）。

        两处要调：合体飞行每帧走完之后，以及**刚吸上的那一帧**。后者容易被漏掉
        ——球是先按自己的动量位移、再判碰撞的，所以吸上的那一刻可能正好有人
        压在墙上；而吸住之后两球就不再各走各的撞墙判定了，那一帧要是没人管，
        这一对就会带着"嵌在墙里"的姿势飞完整整一帧。
        """
        latch = self.latch
        grabber = self.balls[latch.grabber]
        victim = self.balls[latch.victim]
        latch.velocity, impact = self.arena.bounce_rigid_pair(
            grabber, victim, latch.velocity
        )
        if impact is not None:
            self.effects.bounce(impact, grabber.color, latch.velocity.length())

    def update_latch(self, dt: float) -> None:
        """吸住期间的每一帧：整体飞、持续吸取、到点松口。"""
        latch = self.latch
        grabber = self.balls[latch.grabber]
        victim = self.balls[latch.victim]

        # 只走计时器。吸住期间两球不再按各自动量位移，速度那两份暂时是失效的
        grabber.tick(dt)
        victim.tick(dt)

        # 合体飞行：两球整体平移，相对姿势保持不变
        step = latch.velocity * dt
        grabber.position += step
        victim.position += step
        self.correct_latch_walls()

        drained = latch.drain_per_second * dt
        victim.take_damage(drained)
        self.effects.drain_damage(victim.player, victim.position, drained)
        # 吸血：吸出来的补给抓人的一方（上限是满血）。和上面一样，只报真的补进去的
        healed = grabber.heal(drained)
        if healed > 0.0:
            self.effects.heal(grabber.player, grabber.position, healed)

        latch.remaining -= dt
        self.judge()
        if not self.finished and latch.remaining <= 0:
            self.release_latch()

    def release_latch(self) -> None:
        """松口：两球沿连线方向弹开，各自保留合体飞行的那份速度。

        走 set_effective_velocity 而不是直接写 velocity：合体速度是实际速度口径，
        得先按各自的加成分量减回去，否则加速会被算两遍（松口瞬间球会窜快一截）。
        """
        latch = self.latch
        grabber = self.balls[latch.grabber]
        victim = self.balls[latch.victim]

        offset = victim.position - grabber.position
        length = offset.length()
        normal = offset / length if length > 0 else Vector2(1.0, 0.0)
        push = LATCH_RELEASE_SPEED / 2
        grabber.set_effective_velocity(latch.velocity - normal * push)
        victim.set_effective_velocity(latch.velocity + normal * push)

        # 松口即解封。latch.silences 记着这一对当初封没封——绑和封是两件事，
        # 没封过就不能乱解（解了会把别人挂上去的沉默一起抹掉）
        if latch.silences:
            victim.unsilence()

        self.latch = None
        # 松口时两球仍是相切的，复位接触标记；否则下一次真正撞上会被当成"还贴着"而漏掉
        self.touching = False

    def latch_pair(self) -> tuple[Ball, Ball] | None:
        """当前粘在一起的两球（没吸住则为 None），供调试视图画连线用。"""
        if self.latch is None:
            return None
        return self.balls[self.latch.grabber], self.balls[self.latch.victim]

    # ---------------- 胜负 ----------------
    def judge(self) -> None:
        survivors = [player for player, ball in self.balls.items() if ball.alive]
        if len(survivors) == len(self.balls):
            return
        self.finished = True
        # 同时归零则平局
        self.winner = survivors[0] if len(survivors) == 1 else None
