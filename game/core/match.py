"""一局对战的规则与状态。

把"规则"从 app 里抽出来：谁在场上、血量、技能释放、碰撞结算、胜负。
app 只负责界面与主循环，不参与任何判定。

碰撞效果本身不在这里——那是角色的职责（characters/）。Match 只负责
"什么时候问角色"和"拿到主张之后怎么执行"。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from pygame.math import Vector2

from .arena import Arena
from .ball import Ball
from .timescale import TimeScale
from ..characters import Character, CollisionOutcome
from ..fx.effects import Effects
from ..fx.impact import Hit
from ..states.blink import BlinkStrike
from ..states.darkness import Darkness
from ..states.fish import Fish
from ..states.go_board import GoBoard
from ..states.hook import Hook, point_from_end, polyline_length
from ..config.settings import (
    BALL_SPAWN_MIN_GAP,
    BLINK_KNOCKBACK_EPSILON,
    BLINK_SWING_SPEED,
    COLOR_HOOK,
    FUSE_LOCK_SECONDS,
    GO_BOARD_SIZE,
    HITSTOP_FACTOR,
    HOOK_RELEASE_SPEED,
    LATCH_RELEASE_SPEED,
    PLAYER_NAMES,
    SEPARATION_EPSILON,
    SHAKE_EXTRA_BITE,
    SHAKE_EXTRA_SLASH,
    SPLIT_SPAWN_GAP,
    SPLIT_SPREAD_ANGLE,
    TIME_SCALE_DEFAULT,
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

    grabber: Ball            # 抓人的那一颗球
    victim: Ball             # 被绑住的那一颗
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
        # 场上**所有球**：两颗主球 + 所有召唤物（国王的骑士），一张表。
        #
        # 原来这里是 dict[int, Ball]（玩家序号 -> 那颗球），把召唤物挡在门外，
        # 理由是"全场有一大半的机制照着正好两颗球写的"。那是真的，但代价是
        # 每一处"这颗球是哪一边的"都要回头查序号，而序号在召唤物身上是**不唯一**
        # 的——国王和他的骑士共用一个序号，于是每次"找出对面那颗球"都可能摸到
        # 一颗骑士，散落各处的 `target is not owner` 全得改成按边比。
        #
        # 现在反过来：**身份就是球本身**。指向某颗球的地方（钩锁的目标、吸住的
        # 双方、刺客砍的人、棋子归谁）直接存那颗球，不再存一个还要回查的号。
        # player 只剩一个用途——**哪一边**（颜色、敌我、胜负、伤害数字的颜色）。
        #
        # 主球和召唤物的区分落在 Ball.summoned 上：胜负、换位、重开这些"只对
        # 玩家本人成立"的事按它筛（见 mains）。
        self.units: list[Ball] = []
        # 场上**贴在一起的球对**。原来叫 summon_contacts，只记带召唤物的那些
        # 对——主球只有两颗、整场只可能有一对，一个 bool（touching）就够。
        # 现在一个玩家可能有好几块（分裂），"一对一个标记"对全场成立，所以
        # 这份名单管所有对，bool 那一份退役了。
        # 存的是两颗球的 uid（见 Ball.uid），小号在前
        self.contacts: set[tuple[int, int]] = set()
        self.latch: Latch | None = None    # 当前粘在一起的两球
        # 正在降临的黑夜。和 latch 一样是**全场**的东西，不属于哪一颗球——
        # 它盖的是整块战场，顺带把双方的位置和血量对调（见 update_darkness）。
        # 同时只有一个：两个死灵法师同时开，不该换两次把场面换回去
        self.darkness: Darkness | None = None
        # 望的棋盘。和 darkness 一样是**全场**的东西，不属于哪一颗球——它是
        # "战场被划成什么样"，属于场地。两个望对打时共用这一块：各走各的落子
        # 钟（球上的 go_plan），但子落在同一套格子上，不会两颗挤进同一格
        self.go_board: GoBoard | None = None
        # 这一局的时间倍速。base 由左栏滑块拧，技能压的系数每帧申报一次
        self.time_scale = TimeScale(TIME_SCALE_DEFAULT)
        self.finished = False
        self.winner: int | None = None     # finished=True 且 winner=None 表示平局

    # ---------------- 谁在场上 ----------------
    def combatants(self) -> list[Ball]:
        """场上所有**作战单位**：两颗主球 + 所有召唤物。

        每次调用都现拼一个新列表，不是把 self.units 本身递出去。这一点是有意的：
        调用方全是 `for target in self.combatants()` 这种遍历，而遍历途中**伤亡是
        会发生的**（judge 一判就把死掉的骑士从 units 里摘走）。给的是快照，就不
        存在"边遍历边删表"这件事；代价只是各处的循环里那几句 `if not target.alive`
        还得留着——快照里可能躺着一颗刚被打死的球。

        顺序是主球在前、召唤物在后。有几处对顺序是有依赖的（direction_to_opponent
        取"对方那颗主球"来瞄准），主球排前面正好让技能优先冲着对方本人去，
        而不是被路过的骑士带偏。
        """
        return list(self.units)

    def summons(self) -> list[Ball]:
        """场上所有召唤物（当前只有国王的骑士）。"""
        return [ball for ball in self.units if ball.summoned]

    def mains(self) -> list[Ball]:
        """场上所有**玩家本人的球**，按玩家序号排。

        胜负、黑夜换位、重开、选人问的都是它：这几件事只对"玩家选的那个角色
        本人"成立，跟召唤物没关系（骑士死光不算输）。

        **它是一列，不一定两颗**：早先一个玩家一颗球，所以到处都在解包
        `first, second = self.mains()`。分裂一来，一个玩家在场上是好几块
        （gen0 裂成两块 gen1，再各裂成两块 gen2……最多八块），解包就崩了。
        凡是要"一个玩家挑一颗代表"的地方，改用 main_of。
        """
        return sorted((ball for ball in self.units if not ball.summoned),
                      key=lambda ball: (ball.player, ball.uid))

    def bodies(self, player: int) -> list[Ball]:
        """某个玩家在场上的**全部己方身体**：本体 + 分裂出来的半身。

        **不筛死活**：两边的用处不一样——血条要的是"活着的加起来"（见
        side_hp），黑夜换血要的是"一共有几块、各是多大"。筛不筛由调用方说了算。
        """
        return [ball for ball in self.units
                if not ball.summoned and ball.player == player]

    def picked_players(self) -> list[int]:
        """已经选好角色的玩家序号。"""
        return sorted({ball.player for ball in self.mains()})

    def main_of(self, player: int) -> Ball | None:
        """某个玩家**代表那一颗**球（uid 最小的那块，也就是本体或最老的一代）。
        还没选角色时为 None。

        只该用在"一个玩家要挑一颗出来"的地方（血条、技能条、重开造球），
        不能拿它代表这个玩家的全部身家——分裂之后他的血散在好几块上，
        问总量要走 side_hp。
        """
        for ball in self.units:
            if not ball.summoned and ball.player == player:
                return ball
        return None

    def side_hp(self, player: int) -> float:
        """这一边现在一共多少血：**所有活着的块加起来**（用户定的"算总血量"）。"""
        return sum(ball.hp for ball in self.bodies(player) if ball.alive)

    def side_hp_ratio(self, player: int) -> float:
        """这一边还剩几成血，0~1。

        分母取**角色的 max_hp**，不是"当前这些块的上限之和"：分裂和融合都不改
        总量（一块 500 的裂成两块 250，合回来又是 500），所以角色那个数一直是
        这个玩家的满血线。用它当分母，血条就不会因为裂了一次而跳一下。
        """
        main = self.main_of(player)
        if main is None or main.character.max_hp <= 0:
            return 0.0
        return max(0.0, min(1.0, self.side_hp(player) / main.character.max_hp))

    @staticmethod
    def same_side(owner: Ball, target: Ball) -> bool:
        """这两颗球是不是一边的。

        判的是 player（"站哪一边"）而不是"是不是同一颗球"。主球时代这两个问法
        等价——一颗球一个玩家，`target is owner` 就够了——所以各处写的都是后
        者。多了骑士就不等价了：国王的骑士和国王是同一个 player、却是两颗球。

        这个函数替掉的是那些 `if target is owner` 的排除（光环、激光、蛛丝、
        毒刺、刀、锤子、穿刺）。替换之后那些地方的意思从"自己不留神伤到自己"
        变成"这一边不留神伤到自己人"——用户定的"骑士碰到自己不会互相造成伤害"
        是同一条规矩，只不过那是撞，这是技能。
        """
        return target.player == owner.player

    # ---------------- 组装 ----------------
    def both_picked(self) -> bool:
        # 数的是**玩家**不是球：一个玩家分裂成八块也还是一个人选好了
        return len(self.picked_players()) == len(PLAYER_NAMES)

    def pick(self, player: int, character: Character) -> None:
        """给某个玩家换上角色，在场上随机位置满血生成。"""
        self.units = [
            ball for ball in self.units if ball.summoned or ball.player != player
        ]
        self.units.append(self._spawn(player, character, self._others(player)))
        self.reset_outcome()

    def restart(self) -> None:
        """保留已选角色，重新随机位置与动量；血量、技能、胜负全部复位。"""
        placed: list[Ball] = []
        rebuilt: list[Ball] = []
        # **一个玩家只重建一块**，而且重建的是本体（满血满尺寸）。照着 mains()
        # 一颗一颗来是不行的：上一局裂出来的半身也在那一列里，重开会照着一堆
        # 半身造出一堆半身，开局就是八块碎片
        for player in self.picked_players():
            ball = self.main_of(player)
            fresh = self._spawn(player, ball.character, placed)
            rebuilt.append(fresh)
            placed.append(fresh)
        # 只留下重建的那些：上一局的召唤物跟着 reset_outcome 一起勾销
        self.units = rebuilt
        self.reset_outcome()

    def reset_outcome(self) -> None:
        self.contacts.clear()
        # 召唤物和场上那些账本一样要一笔勾销：它是上一局那个国王召出来的，
        # 换角色、重开之后场上不该还飞着别人的兵
        self.units = [ball for ball in self.units if not ball.summoned]
        self.latch = None
        self.darkness = None
        self.finished = False
        self.winner = None
        # 绑住被一笔勾销，挂在人身上的沉默、飞在半路的钩锁、画在墙上的激光、
        # 绷出去的蛛丝也得跟着走，否则重开之后有一方会带着莫名其妙的封印、
        # 渔夫会定在原地动不了、上一局切出来的那些线还会继续割人
        for ball in self.units:
            ball.unsilence()
            ball.hook = None
            ball.fishes = None
            ball.lasers = None
            ball.webs = None
            ball.spikes = None
            # 毒是挂在**中毒的人**身上的减益，和上面那批账本不同，所以重开时
            # 两个人身上都要清——谁中过毒光看"留下了什么"是找不到的
            ball.venom = None
            # 踩到棋子那一下的减速同理：它挂在被踩的人身上，不看"谁留了什么"
            ball.slow = None
            ball.thrust = None
            # 闪现突袭是"技能生效中"的标记：留着它，重开之后刺客会带着一个
            # 指向上一局那个玩家的挥砍状态复活，而那个序号可能已经换人了
            ball.blink = None
            # 刀、锤、棋盘钟不在这里清——它们是常驻被动，跟血量一样属于"球生来
            # 就有的东西"，由 on_spawn 在造球的时候挂上。重开时球是新建的，
            # 自然是新的
        self.effects.clear()
        # 棋盘放在**最后**对账：它要看着整个阵容才能决定自己该不该在场
        # （有望才有棋盘），而且重开时得把上一局那些没主的子清掉
        self.sync_go_board()

    # ---------------- 时间 ----------------
    def begin_frame(self) -> None:
        """每帧开头重收一次"谁要让时间/画面变样"的申报。

        和 Ball.speed_scale 是同一个套路：每帧从零开始，谁要谁申报。
        申报式的代价就是"忘了申报等于解除"，所以这个清空必须在最前面。

        新加一个"放慢时间"的技能，就在这里加一句；它压多少由技能自己带
        （见 core/timescale.py 里对"为什么不做成带时长的减速"的说明）。
        """
        self.time_scale.reset()
        self.effects.reset_screen()

        for ball in self.combatants():
            blink = ball.blink
            if blink is not None and blink.flashing:
                # 键按**球的编号**发，不按玩家序号：序号在一场里只保证"两边不同"，
                # 而这张表是"这一个减速是谁在压"的名册，一颗球一条才说得通
                self.time_scale.push(f"blink:{ball.uid}", blink.slow_factor)
                self.effects.set_vignette(blink.flash_ratio)

        darkness = self.darkness
        if darkness is not None and darkness.slowing:
            self.time_scale.push("nightfall", darkness.slow_factor)

        # 碰上的那一下顿帧（见 fx/impact.py）。它也是"减速"的一种，用同一个
        # 时间倍速，所以和滑块、技能减速是**相乘**的——顿帧叠在慢动作上还是慢动作
        if self.effects.hits.stopping:
            self.time_scale.push("hitstop", HITSTOP_FACTOR)

    def opponent(self, ball: Ball) -> Ball | None:
        """对面**离它最近的那一块**——不是"随便另一颗球"。

        召唤物不算数：瞄准、穿刺、闪现这一路"我要冲谁"的决定冲的都是对方本人，
        骑士是挡在路上的东西、不是目标（见 direction_to_opponent）。场上只剩
        自己时是 None（正常对局走不到，但技能别因此炸掉）。

        **取最近的**：一个玩家只有一颗球时无所谓远近（原来就是直接拿那一颗），
        分裂之后对面可能有好几块，这时候"最近的那一块"才是瞄准真正要问的问题
        ——冲场上最远的那块碎片纯属浪费一次冷却。
        """
        return self.nearest_enemy(ball, ball.position)

    def _others(self, player: int) -> list[Ball]:
        """别的玩家本人的球。排出生点用——召唤物不参与，它们不占位置上的坑。"""
        return [
            ball for ball in self.units
            if not ball.summoned and ball.player != player
        ]

    def _spawn(self, player: int, character: Character, others: list[Ball]) -> Ball:
        position = self.arena.random_spawn_point(
            character.radius, others, gap=BALL_SPAWN_MIN_GAP
        )
        ball = Ball.spawn(player, character, position)
        # 常驻的东西在这里挂上（绕身刀、巨锤）。放在造好之后而不是 Ball.spawn 里，
        # 是因为它们要读球的朝向——刀和锤从哪个角度开始转，得等朝向定下来才知道
        character.attach_passives(ball, self)
        return ball

    # ---------------- 推进 ----------------
    def update(self, dt: float) -> None:
        # 本帧谁要让时间慢下来，先收一遍申报，**必须在算 dt 之前**。
        # 它同时清掉上一帧的画面状态（暗角），所以放在最前面
        self.begin_frame()
        real_dt = dt                     # 顿帧要按真实时间倒计时，见下面的说明
        dt *= self.time_scale.scale

        # 特效先推进，而且放在 finished 判断**之前**：分出胜负的那一下也得把
        # 圈炸完、把数字飘完，不能打死人的瞬间画面就定住了
        self.effects.update(dt, real_dt)
        # 黑夜放在 finished 判断**之前**：打死人的那一下要是正好在黑屏里，
        # 画面也得淡回来，不能永远黑在那儿
        self.update_darkness(dt)
        if self.finished:
            return

        # 减速是"本帧有效"的，所以每帧都先把折扣抹回 1.0，再由光环重新打上去。
        # 必须在这里无条件做，不能等 apply_auras 里去管：放光环的球可能中途死掉，
        # 那条还原路径就断了，折扣会永久留在对方身上，越叠越慢直到停住。
        for ball in self.combatants():
            ball.reset_speed_scale()
        self.apply_auras(dt)
        # 激光和光环同一批结算：都是"场上的东西每帧对球做什么"，而且都不关心
        # 球这一刻在不在动。放在吸住/钩锁的提前返回之前，所以被吸住、被拖着的
        # 人也照样会被线打到——线是画在墙上的，跟谁在动没关系
        self.apply_lasers(dt)
        self.apply_blades(dt)
        self.apply_hammers(dt)
        self.apply_webs(dt)
        # 毒刺和中毒也在这批里：刺钉在墙上、毒在身体里，两样都不看谁在动。
        # 顺序是"先扎后毒"——这一帧新扎上去的毒立刻就开始算，同时扎上三四层
        # 时不会因为顺序问题少算一帧
        self.apply_spikes(dt)
        self.apply_venoms(dt)
        # 挥砍和上面那批一样：不看谁在动。刺客已经贴上去了，对方被吸住、被
        # 钩子拖着也照样砍
        # 棋盘也在这批里：落子**按时间**发生，不看谁在动——钟一到就落一手，
        # 被吸住、被拖着的人照踩不误。减速排在棋盘**后面**：这一帧刚踩上去的
        # 那一下这一帧就开始生效，晚一帧的话踩中的瞬间球还是全速（和"先扎后毒"
        # 是同一个理由）
        self.apply_go(dt)
        self.apply_slows(dt)
        self.update_blinks(dt)
        # 鱼和上面那批同一批：放出去就自己游，渔夫被吸住、被拖着也照样追人
        self.update_fishes(dt)
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

        # 穿刺也是"位置归别人管"的一种，在位移之前推它
        self.update_thrusts(dt)
        if self.finished:
            self.keep_inside(victim)
            return

        for ball in self.combatants():
            # 甩钩锁的人定在原地，被钩回来的人由折线拖着走，正在冲的那位由
            # 穿刺的方向和速度决定位置——三种都不按各自的动量位移。
            # 但计时器照走，否则技能冷却和生效时长会被冻住。
            # 骑士三种都不是（它不甩钩、不被钩、不穿刺），所以一律走 update——
            # 它按自己的动量飞，这就是"向周围发射出去"的全部实现
            if ball.frozen or ball is victim or ball.thrust is not None:
                ball.tick(dt)
            else:
                ball.update(dt)

        self.cast_ready_skills()
        # 碰撞只有这一趟，主球、骑士、分裂出来的半身全在里面（见 resolve_collisions）
        self.resolve_collisions()
        if self.latch is not None:
            # 这一帧刚吸上。不能再走各自的撞墙判定——那会把粘住的一对拆开，
            # 但这一对的边界还是得守（见 correct_latch_walls）
            self.correct_latch_walls()
            # 骑士不参与吸住，而上面那个 return 会把它们一起带走——少了这一句，
            # 一场几秒的吸住里骑士会直接穿墙飞到场外
            self.keep_summons_inside()
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
        for ball in self.combatants():
            self.keep_one_inside(ball, victim)

    def keep_summons_inside(self) -> None:
        """吸住期间**只**守召唤物的边界。

        吸住那一分支是提前返回的（主球的位置由连体位移接管了，不能再按各自的
        反弹判定），走不到 keep_inside。召唤物不参与吸住，所以它得在那边单独补
        一次——不然一场几秒的吸住里，骑士会照着自己的动量一路穿出墙外。

        没有 victim 这一项：被吸住的一定是主球，召唤物永远不是。
        """
        for unit in self.summons():
            self.keep_one_inside(unit, None)

    def keep_one_inside(self, ball: Ball, victim: Ball | None) -> None:
        """守一颗球的边界。上面的判定拆出来，是为了让吸住那一分支也能单独
        拿它来管召唤物（见 keep_summons_inside）。"""
        if ball.frozen or ball is victim or self.finished:
            self.arena.clamp_inside(ball.position, ball.radius)
            return
        hit = self.arena.bounce_off_walls(ball)
        if hit is not None:
            self.effects.bounce(hit.point, ball.color, ball.speed)
            # 撞墙这件事光有几何还不够，被动技能要听这一声（激光、蛛丝、
            # 毒刺）。主动技能走 cast_ready_skills，被动技能走这里。
            # 问的是**角色**不是它的 skill ——被动不一定填在 skill 那一栏，
            # 见 Character.on_wall_hit
            ball.character.on_wall_hit(ball, self, hit.point, hit.side)

    # ---------------- 钩锁 ----------------
    def update_hooks(self, dt: float) -> None:
        """推进场上所有钩锁：在飞的接着飞，在收线的接着拉。"""
        for ball in self.combatants():
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
        # 鱼线还剩多长。折线每帧正好长 speed*dt（弹墙只是把这一段折成两截，
        # 总长不变），所以"这一帧会不会把线走完"是可以提前算出来的
        speed = hook.velocity.length()
        line_left = hook.max_length - polyline_length(hook.path)
        ran_out = False
        if speed > 1e-9 and speed * dt >= line_left:
            # 这一帧只走到线的尽头，不多走：多走的那一截要么得砍掉折线的拐角
            # （绳子会穿过墙），要么钩尖会冲到线外去（画出来收不回来）
            dt = max(0.0, line_left / speed)
            ran_out = True

        start = Vector2(hook.position)
        hook.position += hook.velocity * dt
        target = Vector2(hook.position)

        if self.arena.bounce_point(hook.position, hook.velocity):
            hook.path[-1] = self.arena.wall_crossing(start, target)   # 钉死这一段的拐角
            hook.path.append(Vector2(hook.position))                  # 折回场内，新一段
            self.effects.bounce(hook.path[-2], COLOR_HOOK, hook.velocity.length())
        else:
            hook.path[-1] = Vector2(hook.position)

        # 钩得到**谁**：对面本人的球，也包括对面召出来的骑士——骑士和普通球
        # 一样会中招（用户定的），钩锁没有理由单把它漏掉。
        #
        # 排除条件从"是不是自己"（other is owner）换成"是不是自己一边"：
        # 主球时代这两问等价，有了骑士就不等价了——钩到自家的骑士会被拖着走，
        # 而钩锁是渔夫唯一的输出，白甩一次等于罚站
        for other in self.combatants():
            if other is owner or self.same_side(owner, other) or not other.alive:
                continue
            if (other.position - hook.position).length() > other.radius:
                continue
            self.hook_hit(owner, other, hook)
            return

        if ran_out:
            self.hook_missed(owner, hook)

    def hook_missed(self, owner: Ball, hook: Hook) -> None:
        """钩空了：鱼线放完也没咬到人，改成在钩子那儿放一条鱼出去追。

        用户定的这一条把"甩空"从纯粹的惩罚变成了**另一种结果**：宁可钩空也不
        要白甩一次，放出来的那条鱼会自己去追人。鱼的体型是随机的，咬得重不重、
        活多久全看这一下运气。

        **有一定概率连鱼都放不出来**（用户定的 fail_chance）：这是同一个随机
        里面更差的那一档，钩空 + 召唤失败才是真的白甩一次。两种结果都走
        finish_skill 收尾——技能总得结束、冷却总得开始走，不然渔夫会永远定在
        那里（钩锁是他唯一的输出，卡住一次就再也动不了了）。

        放出来的鱼是从**钩子当前位置**出发的（不是渔夫身上）：这就是"从钩子处
        召唤"，钩子飞到哪儿，鱼就从哪儿下水。

        **放鱼这一刻技能就收招、冷却就开始走**（用户定的"召唤出鱼之后技能就
        可以进入冷却了"）。所以顺序是：先 finish_skill 再 cast_fish，反过来
        不行——finish_skill 会清 hook（这里正好要清），但鱼要是先挂上去了、
        再走一遍收招，就得额外小心别把它一起清掉。先收招再放鱼，鱼是收招之后
        才落到水里的东西，跟技能已经没关系了。
        """
        spec = hook.fish_spec
        owner.finish_skill()
        if random.random() < spec.fail_chance:
            return
        # 收招之后才放：这条鱼是"放出去就不管了"的账本（见 Ball.fishes），
        # 水里游多久、咬不咬得到，都不再牵动渔夫那条技能——冷却已经在上面
        # 那一刻开始走了，鱼只是还在那儿游着
        self.cast_fish(owner, Vector2(hook.position), hook)

    def cast_fish(self, owner: Ball, position: Vector2, hook: Hook) -> None:
        """在 position 放一条鱼，体型随机，朝最近的敌人游过去。

        数值（半径、伤害、活多久）都在这一刻按体型算好烤进 Fish 里——同
        WebAnchor / GoStone，之后调角色参数不会把水里已有的那条鱼一起改掉。

        伤害和持续时间都**正比于体型**（用户定的"根据大小造成伤害与持续时间"）：
        一个随机半径乘两个比例，两样东西就都跟着大小走了，不需要再各配一套
        上下限。所以"大鱼"的价值是双份的——咬得更重，而且有更多时间追上第二口。

        初始速度直接朝目标：鱼是放出来追人的，一上来先原地转一圈找方向很蠢。
        目标就是最近的那个敌人（含对面的骑士），找不到就朝渔夫的朝向游。

        **往 fishes 里追加，不是覆盖**：技能收招之后冷却就在走，冷却一走完
        渔夫就能再甩第二钩，那时候水里这条可能还没咬完。单槽的话第二次放鱼会
        把它顶掉，等于凭空少咬一口（和 webs / spikes 同一个账本口径）。
        """
        spec = hook.fish_spec
        size = random.uniform(spec.min_size, spec.max_size)
        target = self.nearest_enemy(owner, position)
        if target is not None:
            offset = target.position - position
            heading = offset.normalize() if offset.length_squared() > 1e-12 \
                else Vector2(owner.heading)
        else:
            heading = Vector2(owner.heading)

        lifetime = size * spec.duration_per_size
        if owner.fishes is None:
            owner.fishes = []
        owner.fishes.append(Fish(
            position=Vector2(position),
            velocity=heading * spec.speed,
            radius=size,
            damage=size * spec.damage_per_size,
            remaining=lifetime,
            total=lifetime,
            speed=spec.speed,
            turn_rate=spec.turn_rate,
            turn_slow=spec.turn_slow,
        ))

    def nearest_enemy(self, owner: Ball, position: Vector2) -> Ball | None:
        """离 position 最近的敌人（含对面的骑士）。没有则 None。"""
        best = None
        best_distance = 0.0
        for unit in self.combatants():
            if not unit.alive or self.same_side(owner, unit):
                continue
            distance = (unit.position - position).length_squared()
            if best is None or distance < best_distance:
                best, best_distance = unit, distance
        return best

    # ---------------- 鱼 ----------------
    def update_fishes(self, dt: float) -> None:
        """推进场上所有的鱼：追人、咬一口、到点消失。

        和光环、激光、蛛丝同一批结算，都放在吸住/钩锁的提前返回之前——鱼是
        放出去自己游的，渔夫被吸住、被钩着拖着它也照样在追人。

        咬中就走：鱼是**一发**东西，不是一颗站得住的球（见 states/fish.py）。
        所以这里一咬中就把它清掉，不像骑士那样留下来接着打。

        判定用"鱼心和敌人圆面挨上"（半径和），和钩锁撞人的口径一致。

        鱼没了的三条路（主人死了 / 到点了 / 咬到了）**都只是把它从账本上划掉**，
        **不碰技能**：放鱼那一刻技能就已经收招、冷却就已经在走了（见
        hook_missed）。这里再调一次 finish_skill 的话等于把冷却重新拨满，
        冷却会被这条鱼无限往后推——收招过一次的技能不能再收第二次。

        按 `list(...)` 遍历是因为循环体里会从 fishes 里删鱼，直接迭代原表会
        跳元素。同一帧可能有好几条鱼在游（冷却短的时候前一发还没咬完）。
        """
        for owner in self.combatants():
            if not owner.fishes:
                continue
            if not owner.alive:
                # 主人没了，他放的鱼跟着作废（不然会替一颗死球接着咬人）
                owner.fishes = None
                continue

            for fish in list(owner.fishes):
                fish.remaining -= dt
                if fish.remaining <= 0.0:
                    owner.fishes.remove(fish)
                    continue

                target = self.nearest_enemy(owner, fish.position)
                if target is not None:
                    fish.steer(target.position, dt)

                for victim in self.combatants():
                    if not victim.alive or self.same_side(owner, victim):
                        continue
                    reach = fish.radius + victim.radius
                    if (victim.position - fish.position).length() > reach:
                        continue
                    victim.take_damage(fish.damage)
                    # 环炸在**鱼身上**（见 Hit.at）：咬人的是这条鱼，不在任何一颗球上
                    self.effects.hits.strike(Hit.at(
                        fish.position, victim, fish.damage,
                        speed=(fish.velocity - victim.effective_velocity).length(),
                    ))
                    owner.fishes.remove(fish)
                    break
        self.judge()

    def hook_hit(self, owner: Ball, victim: Ball, hook: Hook) -> None:
        """钩中了：把对方拽到钩尖上，并把收线要走的折线准备好。"""
        hook.target = victim
        # 钩住期间对方被**沉默**：钩中人是从咬住那一刻算起的，一直到松手为止
        # （中途有人没了就在 reel_hook 那条早退里解封）。和吸住那条沉默是同一个
        # 通用机制——封的是"开"这个动作，已经在生效的技能照常走完，冷却照常走
        victim.silence()
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
        victim = hook.target
        if victim is None or not victim.alive or not owner.alive:
            # 有人没了，钩锁随即作罢。走 finish_skill 收尾，好让冷却从这一刻开始
            owner.finish_skill()
            # 钩没收到头就断了，被钩住那位的沉默得在这里解掉——解封是施加方的
            # 责任，没人替他做（reset_outcome 也会兜一次，但那是重开时才走的）
            if victim is not None:
                victim.unsilence()
            return

        before = Vector2(victim.position)
        hook.pulled = min(hook.total, hook.pulled + hook.pull_speed * dt)
        # 钩尖跟着被拖的人一起往回走。**这一句是画绳子用的**：绳子按 pulled
        # 截断画，钩尖不动的话看着就像钩子挂在原地、只有人被拽过来
        hook.position = point_from_end(hook.path, hook.pulled)
        victim.position = Vector2(hook.position)

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

        # 松手即解封（见 hook_hit）。和吸住一样：绑多久封多久，解封是施加方的事
        victim.unsilence()
        owner.finish_skill()
        # 推完之后两人是分开的，清掉接触标记；否则下一次真撞上会被当成"还贴着"漏掉
        self.forget_contact(owner, victim)

    def pulled_pair(self) -> tuple[Ball, Ball] | None:
        """当前正被钩锁往回拖的那一对（渔夫, 敌人），没有则为 None。"""
        for ball in self.combatants():
            hook = ball.hook
            if hook is not None and hook.reeling and hook.target is not None:
                return ball, hook.target
        return None

    def _is_pulled_pair(self, first: Ball, second: Ball) -> bool:
        pair = self.pulled_pair()
        return pair is not None and first in pair and second in pair

    def cast_ready_skills(self) -> None:
        """技能自动释放：冷却一好就放，玩家不需要操作。吸住期间不释放。

        两栏都问：主球用玩家选的那个技能，召唤物用它自己带的（骑士的是
        IdleSkill——那一栏的 ready 永远回 False，所以骑士一辈子不会被这里点到）。
        遍历范围是全部单位，不是只挑主球：以后哪个召唤物配了真技能，这里不用改。
        """
        for ball in self.combatants():
            if ball.alive:
                ball.activate_skill(self)

    # ---------------- 召唤 ----------------
    def summon_knights(self, owner: Ball, knight: Character, count: int,
                       launch_speed: float) -> None:
        """从 owner 身上朝四周均匀甩出 count 个骑士，之后就交给它们自己飞。

        和 NightfallSkill 调 start_darkness 是同一个分工：技能管"召几个、多快"，
        造球和摆位置留在 Match——造一颗球要走 Arena（出生点得躲开别人、得夹在
        场内），球不知道战场在哪。

        方向基准取**国王自己的朝向**（同 Ball.start_blade：写死一个起始角的话，
        两边同时放技能会像同步的机械，跟着朝向走才一眼看得出这批骑士是从谁身上
        出来的）。360° 均分，所以三个骑士正好是 120° 一个。

        出生点摆在自己身外一圈（owner.radius + knight.radius）：摆在身子底下的话
        三个骑士会和国王叠在一起，得靠后面几帧的碰撞分离慢慢挤开——那是"渗出来"
        不是"甩出去"，而且分离那几帧里它们的位置是被人推着走的，初速度根本看不
        出来。摆到刚好相切，第一帧起就是干净的三条直线。

        贴墙放技能时有一个骑士会被摆到墙外，所以摆完立刻夹一次（clamp_inside）：
        反正它这一帧还要走撞墙判定，夹回来就行。

        召出来的骑士是 summoned=True 的球，进的是和两颗主球同一张 units 表——
        它在场上就是一个普通的作战单位，只是不参与胜负、换位、重开那几件事
        （见 mains）。
        """
        base = math.atan2(owner.heading.y, owner.heading.x)
        for index in range(count):
            angle = base + math.tau * index / count
            direction = Vector2(math.cos(angle), math.sin(angle))
            position = owner.position + direction * (owner.radius + knight.radius)
            baby = Ball.spawn(owner.player, knight, position,
                              direction * launch_speed, summoned=True)
            self.arena.clamp_inside(baby.position, baby.radius)
            # 和 Match._spawn 一样问一遍常驻被动。骑士现在两栏都是空的，所以这一步
            # 什么都不做——留着是为了以后给骑士配了被动时不会悄悄漏掉
            knight.attach_passives(baby, self)
            self.units.append(baby)

    # ---------------- 范围光环 ----------------
    def apply_auras(self, dt: float) -> None:
        """结算范围光环：圈内的敌人被减速，并被持续吸取（吸出来的补给圈的主人）。

        判定用**圆心**是否落在圈内，和画出来的那个圈严格一致（不是"圆面相交"）。
        所以贴着圈边站还能吃到，圆心一出圈就立刻恢复——减速不残留。

        **自己一边的不吸**（见 same_side）：圈的主人自己的骑士站在圈里也照样
        吃满速度，不然国王召完骑士就得看着它们被自己的圈拖慢。
        """
        for owner in self.combatants():
            aura = owner.aura
            if aura is None or not owner.alive:
                continue
            for target in self.combatants():
                if self.same_side(owner, target) or not target.alive:
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
        for owner in self.combatants():
            grid = owner.lasers
            if grid is None or not grid.beams or not owner.alive:
                continue
            for target in self.combatants():
                if self.same_side(owner, target) or not target.alive:
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

    # ---------------- 绕身刀 ----------------
    def apply_blades(self, dt: float) -> None:
        """结算绕身刀：转一步，蹭到的敌人扣一次血，**每转一圈最多蹭一次**。

        和激光、光环同一批：都是"场上的东西每帧对球做什么"。放在吸住/钩锁的
        提前返回之前，所以被吸住、被拖着的人也照样会被刀刮到——刀是长在武士
        身上的，跟谁在动没关系。

        判定用刀那一截线段到敌人圆心的距离，而不是"两个球挨上了"：刀是伸出去
        的，武士本人离敌人还有一段距离就该刮得到。

        自己的刀不伤自己，和激光同理。
        """
        for owner in self.combatants():
            blade = owner.blade
            if blade is None or not owner.alive:
                continue
            blade.advance(dt)
            for target in self.combatants():
                if self.same_side(owner, target) or not target.alive:
                    continue
                if not blade.hits(owner.position, target.position, target.radius):
                    continue
                # 转过去的这一圈已经刮过它了——刀压在敌人身上是每帧都"挨着"的，
                # 少了这一问，一秒就是 60 下
                if not blade.consume(target.uid):
                    continue
                target.take_damage(blade.damage)
                # "撞得多快"取**刀尖**速度，不是武士自己的：站着不动的武士照样
                # 能用转着的刀削人，看球速会把这一下算成 0
                tip = blade.tip_velocity(owner.effective_velocity)
                self.effects.hits.strike(Hit.on(
                    owner, target, blade.damage,
                    speed=(tip - target.effective_velocity).length(),
                ))
        self.judge()

    # ---------------- 巨锤 ----------------
    def apply_hammers(self, dt: float) -> None:
        """结算大锤：抡一步，锤头砸到的敌人挨一锤，**每抡一圈最多一次**。

        和刀、激光、光环同一批：都是"场上的东西每帧对球做什么"。放在吸住/钩锁
        的提前返回之前，所以被吸住、被拖着的人也照样会挨锤——锤子是长在大锤
        身上的，跟谁在动没关系。

        这一锤比刀多两件事，都在 Hammer.impact 里算：

        - **打飞**：对方的速度整个重写成"撞上一面以锤头速度移动的无限质量墙"
          的结果（v' = 2u - v）。不是加一股冲量，是直接换速度——所以迎面冲过来
          的敌人会被弹得比站着不动的更远。
        - **伤害按相对速度平方**：对方自己在往锤子上撞，那一下就比站着挨打重。

        **霸体的人打不飞，但照样掉血**：霸体顶替的是"被推动"，不是"被碰上"，
        和渔夫那条"霸体只顶替被推动、伤害照常两边各算各的"是同一条原则。谁是
        霸体统一问 has_super_armor——**是它，不是 ball.frozen**：光看 frozen
        只会挡住甩钩锁的渔夫，被吸住的那一对照样会被锤飞，而吸住期间两球的速度
        本来就由连体位移接管，那一锤等于白写。打不飞的人会一直待在锤子的道上，
        全靠每圈一次那张名单兜着。

        自己的锤子不砸自己，和刀同理。
        """
        for owner in self.combatants():
            hammer = owner.hammer
            if hammer is None or not owner.alive:
                continue
            hammer.advance(dt)
            for target in self.combatants():
                if self.same_side(owner, target) or not target.alive:
                    continue
                if not hammer.hits(owner.position, target.position, target.radius):
                    continue
                # 抡过去的这一圈已经砸过它了——锤头压在敌人身上是每帧都"挨着"的，
                # 少了这一问，一秒就是 60 下
                if not hammer.consume(target.uid):
                    continue
                before = Vector2(target.effective_velocity)
                launched, damage = hammer.impact(
                    owner.effective_velocity, target.effective_velocity
                )
                # 打飞出去多少，按**实际落下去的那一下**算。霸体的球不吃这一推，
                # 那它就没被打飞，额外震动自然也不该有——所以先判霸体再看速度
                knockback = 0.0
                if not self.has_super_armor(target):
                    target.set_effective_velocity(launched)
                    knockback = (launched - before).length()
                target.take_damage(damage)
                # "撞得多快"取**锤头**速度，它才是砸上去的那个东西
                self.effects.hits.strike(Hit.on(
                    owner, target, damage,
                    speed=hammer.head_velocity(owner.effective_velocity).length(),
                    knockback=knockback,
                ))
        self.judge()

    # ---------------- 闪现突袭 ----------------
    def start_blink(self, ball: Ball, target: Ball, distance: float,
                    flash_seconds: float, slow_factor: float,
                    slash_seconds: float, blink_interval: float,
                    reach: float, slash_damage: float,
                    exit_speed: float) -> None:
        """起手：闪到目标**身后**一段距离，砍第一刀，然后开始数连招的钟。

        "身后"取的是**敌人运动方向的反面**（target.heading），不是"相对刺客的
        另一侧"。所以起手是咬尾巴，不是穿过去：敌人往哪飞，刺客就落在它屁股后头。
        后面每一刀的落点则是随机挑的（见 blink_to_side），只有这第一下有讲究。

        落点用 heading 而不是速度矢量，是因为两球正面对撞后速度可能被清成 0
        ——那种时候 heading 还留着上一帧的朝向，是唯一还有意义的方向（见
        Ball.effective_velocity 里对 heading 的说明）。

        闪现是**当场**换位置，不走过场：flash 那一段纯粹是演出（暗角 + 减速），
        位置在技能放出来这一帧就已经到了。演出比位移长一点是有意的——"闪过去
        了"这件事得有个能被看见的瞬间。

        **挥砍期间速度为 0**（用户定的）：刺客定在原地，位置全靠闪现换。所以
        这里先把速度摁掉，之后每一帧 update_blinks 都会再摁一次——碰撞那几趟
        跑在位移之后，不每帧摁的话会被上一帧的弹开速度推着走。
        """
        strike = BlinkStrike(
            target=target,
            facing=Vector2(1.0, 0.0),
            slash_remaining=slash_seconds,
            slash_total=slash_seconds,
            flash_remaining=flash_seconds,
            flash_total=flash_seconds,
            slow_factor=slow_factor,
            slash_damage=slash_damage,
            blink_distance=distance,
            blink_interval=blink_interval,
            next_blink=blink_interval,
            exit_speed=exit_speed,
            reach=reach,
        )
        ball.blink = strike

        behind = target.position - target.heading * distance
        ball.position.update(behind)
        self.arena.clamp_inside(ball.position, ball.radius)
        ball.set_effective_velocity(Vector2(0.0, 0.0))

        # 起手那一下也**要砍**（"闪到对方身边后砍一刀"），所以这条共享的路
        # 直接走一遍：摆朝向、压暗角、结算伤害。区别只是落点已经摆好了，
        # 这里不重新挑位置
        self.slash_from_here(ball, target, strike)

    def blink_to_side(self, ball: Ball, target: Ball, strike: BlinkStrike) -> None:
        """闪到目标**周围随机一个方向**上，然后砍一刀。

        随机取整圈（不是"接着上一个落点转一点"）：用户要的就是"读不出下一刀
        从哪来"。按固定角速度绕着转的话，对方看两刀就能预判第三刀的位置了。
        """
        angle = random.uniform(0.0, math.tau)
        landing = target.position + Vector2(math.cos(angle), math.sin(angle))             * strike.blink_distance
        ball.position.update(landing)
        self.arena.clamp_inside(ball.position, ball.radius)
        self.slash_from_here(ball, target, strike)

    def slash_from_here(self, ball: Ball, target: Ball, strike: BlinkStrike) -> None:
        """站在当前位置砍一刀：摆朝向、重新压一次暗角、结算伤害。

        朝向是"从这里指向敌人"，所以挥砍的弧永远盖在敌人身上。这一条同时替掉了
        原来那个"敌人还在不在面前"的判定（blink_in_reach）——落点是刺客自己挑
        的，每次都在敌人身边，没有"砍空"这一说了。

        暗角**每一刀都重新压一次**：一套连招看下来就是"闪一下、闪一下、闪一下"，
        而不是只有起手黑一次。代价是时间倍速被反复压低（见 begin_frame），嫌
        晃眼就把 flash_seconds 调短——它是这两个效果共用的那个数。
        """
        offset = target.position - ball.position
        if offset.length_squared() > 1e-9:
            strike.facing = offset.normalize()
        strike.flash_remaining = strike.flash_total

        if target.alive:
            target.take_damage(strike.slash_damage)
            self.effects.hits.strike(Hit.on(
                ball, target, strike.slash_damage,
                speed=strike.blink_distance / max(strike.blink_interval, 1e-6),
            ))
        # 起手那一下额外震一份：闪现走不到"命中"那条路上（它是瞬移，没有飞行
        # 过程），但它是这个技能最重的一瞬——和闪现的暗角、减速是同一时刻的三件事
        self.effects.hits.jolt(SHAKE_EXTRA_SLASH)
        strike.slashes += 1
        self.judge()

    def update_blinks(self, dt: float) -> None:
        """推进闪现突袭：数着钟闪过去砍一刀，时间走完就收招。

        和光环、激光、蛛丝同一批：都是"场上的东西每帧对球做什么"。放在吸住/
        钩锁的提前返回之前，所以被吸住、被拖着的人也照样会被砍——刺客已经贴上
        去了，跟谁在动没关系。

        ## 速度为 0 和"被击退"是怎么共存的

        每一帧在这里把速度摁回 0，于是位移那一步它一动不动。但**碰撞那几趟跑在
        位移之后**（见 Match.update），所以这一帧结束时它身上可能留着一份碰撞
        或锤子打上来的速度。于是下一帧进到这里、还没摁之前读到的那个值，就是
        "上一帧有没有人把它推走"，读到了就记进 strike.knockback。

        用"读上一帧残留"而不是去碰撞那几处打标记，是因为推它的来源有好几个
        （球撞球、锤子打飞、以后可能还有别的），一处一处挂标记迟早会漏一个；
        而"这一帧结束时它身上有多少速度"是它们的**共同结果**，一个数就够。
        """
        for ball in self.combatants():
            strike = ball.blink
            if strike is None:
                continue

            strike.swing += dt * BLINK_SWING_SPEED
            if strike.flash_remaining > 0.0:
                strike.flash_remaining = max(0.0, strike.flash_remaining - dt)

            target = strike.target
            if target is None or not target.alive or not ball.alive:
                self.finish_blink(ball, strike)
                continue

            knocked = ball.effective_velocity
            if knocked.length() >= BLINK_KNOCKBACK_EPSILON:
                strike.knockback = Vector2(knocked)
            ball.set_effective_velocity(Vector2(0.0, 0.0))

            strike.next_blink -= dt
            if strike.next_blink <= 0.0:
                # 用 += 而不是 = interval：这一帧超出的那一点留到下一轮，闪的
                # 节奏才不会被帧长带偏（同 Ball.tick 里数冷却的写法）
                strike.next_blink += strike.blink_interval
                self.blink_to_side(ball, target, strike)
                if self.finished:
                    # 这一刀把目标砍死了，连招到此为止
                    continue

            strike.slash_remaining = max(0.0, strike.slash_remaining - dt)
            if strike.slash_remaining <= 0.0:
                self.finish_blink(ball, strike)
        self.judge()

    def finish_blink(self, ball: Ball, strike: BlinkStrike) -> None:
        """收招：按"往敌人反方向离开"或者"被击退的那份速度"把动量还回去。

        两种走法（用户定的）：

        - **正常收招**：朝敌人**反方向**离开，速度取 exit_speed。踉跄退开一步，
          不是停在原地——一颗速度归零的球在这游戏里等于废了（它没有自推能力，
          会一直杵在那儿）。
        - **期间被击退过**：按那份速度走，方向大小原样。挨了一锤还按原计划
          飘走就太假了。

        目标死了或者找不到的时候也没法算"反方向"，退回自己的朝向——总之得给一个
        非零速度出去。
        """
        ball.blink = None
        target = strike.target
        if strike.knockback is not None and strike.knockback.length() > 1e-9:
            ball.set_effective_velocity(Vector2(strike.knockback))
        elif target is not None:
            away = ball.position - target.position
            if away.length_squared() > 1e-9:
                away = away.normalize()
            else:
                away = Vector2(ball.heading)
            ball.set_effective_velocity(away * strike.exit_speed)
        else:
            ball.set_effective_velocity(Vector2(ball.heading) * strike.exit_speed)
        ball.finish_skill()

    # ---------------- 黑夜降临 ----------------
    def start_darkness(self, total: float, caster: Ball | None,
                       slow_factor: float = 1.0) -> None:
        """拉下一次黑夜，记下是谁放的。已经在黑着就不再拉——同时只有一场。

        这不是为了省事：两个死灵法师的技能是同时冷却好的（都是开局就没冷却），
        不挡一下的话两场黑夜会一前一后各换一次位，等于什么都没换。挡掉第二场，
        换位就只发生一次，两边看到的都是对方的场面。

        caster 是"从谁的角度看这次换不换"：换位是个翻盘手段，只有落后的一方放
        才生效（见 nightfall_swap）。两个死灵法师对打时，落后的那位放的黑夜
        会把两人换个个儿，领先的那位放了等于没放。

        slow_factor 是黑屏期间把游戏速度压到几倍。压的是**渐暗 + 全黑**那一段，
        渐亮时恢复（见 Darkness.slowing）：变黑是个"要出事"的过程，慢下来是在
        等那件事发生；变亮是收尾，再拖着慢就没意思了。
        """
        if self.darkness is None:
            self.darkness = Darkness.for_duration(total, caster, slow_factor)

    def update_darkness(self, dt: float) -> None:
        """推进黑屏：黑到底的那一瞬换位，淡完就收工。"""
        darkness = self.darkness
        if darkness is None:
            return
        darkness.elapsed += dt
        if not darkness.swapped and darkness.blacked_out:
            darkness.swapped = True
            # 已经分出胜负就不再换位：对面可能已经死了，把 0 血换过来会连带
            # 把赢家也拖成 0，一场明明打赢了的对局变成平局。
            # 不足两个玩家也没什么可换的（技能是和选人绑的，正常走不到这儿）。
            # 数的是**人**：换位换的是"玩家本人那些球"，骑士不参与
            sides = set(self.picked_players())
            living = {ball.player for ball in self.mains() if ball.alive}
            if len(sides) >= 2 and living == sides:
                self.nightfall_swap(darkness.caster)
        if darkness.finished:
            self.darkness = None

    def nightfall_swap(self, caster: Ball) -> None:
        """黑夜的正题：双方**互换位置与血量**，动量和其他一切都留在原地。

        但**换不换要看放技能的人落后没有**：放的人血量百分比不低于对手时，
        这一场什么都不换（黑屏照播，玩家能看出技能放出来了、只是没生效）。
        所以这不是一个"每冷却好就白拿一次"的位移技，是一个**翻盘**手段——
        残血的时候放才有意义，健康的时候放等于浪费一次冷却。

        血量换的是百分比（两个角色的 max_hp 不保证一样大，直接对调数值会爆表），
        而且量的是**一整边**的总血量百分比（见 side_hp_ratio）：分裂之后血散在
        好几块上，只换代表那一块的话，一块碎片就能把整个换血搅乱。换完每一边
        各自按自己那些块的上限摊回去，一块一块地兑现。

        位置要挑人换：位置正在被"摆"的一方动不了，硬换等于把它从控制里拽出来。
        用户定下的规则是三种情况不换：

        - 甩着钩锁的渔夫（霸体，定在原地）——连他一块不换，因为换位是**一对**
          的事，他不动，对面也就没有"另一个位置"可以换过去；
        - 正被钩锁拖回来的人（位置由折线定，同样是被摆的）；
        - 吸住的一对（连体位移期间两人都算伪霸体：会一起飞，但不受外力影响）。

        穿刺不在此列：它只是"这颗球自己沿着一个方向在走"，位置还是自己的，
        而且打没打中是每帧实时判距离的（见 check_thrust_hit），换完接着冲就是。

        分裂过来的那一堆还多一条：**哪一边不止一块，位置就不换**（只换血）。
        换位要的是"我看见的那个场面整个对调"，好几块碎片没法整体搬过去——摆到
        对方的位置上要么散架要么叠成一团。这和上面那三条是同一条原则：位置摆
        不下的一方不动，血照换。
        """
        enemy = self.opponent(caster)
        if enemy is None:
            return
        mine = self.bodies(caster.player)
        theirs = self.bodies(enemy.player)

        # 放的人没落后就什么都不换：黑屏已经黑过了，但场面原样不动。
        # 平手也算"没落后"——不换，免得两边同时残血时互相刷
        my_ratio = self.side_hp_ratio(caster.player)
        their_ratio = self.side_hp_ratio(enemy.player)
        if my_ratio >= their_ratio:
            return

        if len(mine) == 1 and len(theirs) == 1 \
                and not (self.has_super_armor(mine[0]) or self.has_super_armor(theirs[0])):
            mine[0].position, theirs[0].position = (
                Vector2(theirs[0].position), Vector2(mine[0].position)
            )

        # 死了的那些块不参与兑现（换血不该把尸体救活）。所以拿到的那一份是按
        # **活着的那些块**的上限摊开的，总缺口留在已经失去的那块上
        for ball in mine:
            if ball.alive:
                ball.hp = their_ratio * ball.max_hp
        for ball in theirs:
            if ball.alive:
                ball.hp = my_ratio * ball.max_hp

    def has_super_armor(self, ball: Ball) -> bool:
        """这颗球现在是不是**霸体**：位置不由自己说了算。

        三种球：甩着钩锁定住不动的、被钩锁的折线拖着的、被吸住粘成一团飞的
        （吸住是连体位移，两球当一团走，方向已经不由其中任何一方决定）。穿刺
        不算——那只是这颗球自己沿一个方向在跑，随时能停，位置还是自己的。

        霸体的定义**就这一处**，两个地方问它，问的是同一件事的两面：

        - 黑夜降临：位置被摆着的人不能硬挪（会把它从控制里拽出来，钩索断在
          半空），所以那一对只换血不换位。
        - 巨锤：推不动的人打不飞，但**照样掉血**——霸体顶替的是"被推动"，
          不是"被碰上"。跟渔夫那条"霸体只顶替被推动、伤害照常两边各算各的"
          是同一条原则。

        所以别把它当成"夜降临专用"的判据：以后再有"推不动/挪不动"的场合，
        该问的还是这里，不是 ball.frozen（那个只认钩锁，漏掉被吸住的人）。

        比对的是**球本身**而不是玩家序号。序号在这里会认错人：吸住和钩锁记的
        都是序号，而骑士和它的国王共用一个序号——按序号比的话，国王被吸住时
        他的骑士也会被算成霸体，锤子就砸不飞它们了。
        """
        if ball.frozen:
            return True
        latch = self.latch
        if latch is not None and ball in (latch.grabber, latch.victim):
            return True
        pair = self.pulled_pair()
        return pair is not None and any(ball is caught for caught in pair)

    # ---------------- 蛛丝 ----------------
    def apply_webs(self, dt: float) -> None:
        """结算蜘蛛拉的那些丝：压在上面的敌人被减速，并按丝数叠加掉血。

        丝是**一头钉墙、一头连着自己**的，所以这一帧的线要现算：起点是蜘蛛
        现在的位置，不是某个记下来的历史坐标。蜘蛛跑动的时候这把"扇子"整个
        跟着扫，敌人站在哪都可能突然被扫到。

        和光环、激光、刀同一批结算，都放在吸住/钩锁的提前返回之前——被吸住、
        被拖着的人也照样会被丝扫到。蜘蛛自己有霸体也逃不掉这件事：这不属于
        "被推动"。

        **自己的丝不伤自己**，和激光同理。顺带一提，蜘蛛本人永远压在自己的
        每一根丝上（线就从它身上出发），少了这条排除，它开局就在自杀。

        减速取**最狠的那一根**而不是逐根相乘：每根丝都按比例乘一遍的话，几根
        丝叠起来就是指数级地慢，两三下就贴死在原地了。伤害才是叠加的。
        """
        for owner in self.combatants():
            if not owner.webs or not owner.alive:
                continue
            for target in self.combatants():
                if self.same_side(owner, target) or not target.alive:
                    continue
                touched = [
                    web for web in owner.webs
                    if web.touches(owner.position, target.position, target.radius)
                ]
                if not touched:
                    continue
                target.speed_scale = min(
                    target.speed_scale,
                    1.0 - max(web.slow_ratio for web in touched),
                )
                dealt = sum(web.damage_per_second for web in touched) * dt
                target.take_damage(dealt)
                self.effects.drain_damage(target.player, target.position, dealt)
        self.judge()

    # ---------------- 毒刺 ----------------
    def apply_spikes(self, dt: float) -> None:
        """结算墙上的毒刺：碰到的敌人挨一下、中毒，然后这根刺重新蓄力。

        和光环、激光、蛛丝、刀同一批结算，都放在吸住/钩锁的提前返回之前——
        被吸住、被钩着拖的人也照样会被刺扎到，刺是钉在墙上的，跟谁在动没关系。
        被钩锁拖回来那条折线贴着墙走的时候，这一条尤其要紧。

        **自己的刺不扎自己**，和激光、蛛丝同理。

        一次只扎一个人（扎到就 break）：刺是**一根**针，同一瞬间被两个人碰到
        这种情形在这个战场里不存在，但真发生了也该是"先碰到谁算谁"，而不是
        "一根刺同时扎出两份伤害"。蓄力也一并开始，所以另一颗球接着碰也不会
        蹭到连着的第二下。
        """
        for owner in self.combatants():
            if not owner.spikes or not owner.alive:
                continue
            for spike in owner.spikes:
                spike.tick(dt)
                # 没长好的刺不判定——它挂在那儿只是个记号，等蓄满再算
                if not spike.armed:
                    continue
                for target in self.combatants():
                    if self.same_side(owner, target) or not target.alive:
                        continue
                    if not spike.touches(target.position, target.radius):
                        continue
                    spike.consume()
                    target.take_damage(spike.damage)
                    target.poison(spike.poison_seconds, spike.poison_per_second)
                    # 环炸在**刺**那一点上（见 Hit.at）：扎人的东西钉在墙上，
                    # 不在任何人身上。速度取受害者自己的——它是自己撞上来的
                    self.effects.hits.strike(Hit.at(
                        spike.point, target, spike.damage, speed=target.speed,
                    ))
                    break
        self.judge()

    def apply_venoms(self, dt: float) -> None:
        """结算中毒：每层各走各的倒计时，到点掉一层；还在走的那些每秒扣血。

        **毒不分敌我，也不认下毒的人**：谁中的毒就扣谁的血，下毒的那位中途
        死掉，毒照样走完。它不是挂在毒刺身上的持续效果，是已经进了对方身体里
        的东西——这一点和 silence 同类，和 lasers / webs 那类"我留下了什么"
        的账本正相反。

        掉血走 effects.drain_damage（红字、攒着报），和吸血、激光、蛛丝同一路：
        都是每帧结算的持续伤害，一帧飘一个数字会糊成一片。也**不震屏**——这个
        游戏里"震"的含义是"挨了一下"，中毒是"在掉血"（见 fx/impact.py）。
        """
        for ball in self.combatants():
            if not ball.venom or not ball.alive:
                continue
            kept = []
            dealt = 0.0
            for stack in ball.venom:
                if stack.tick(dt):
                    continue
                kept.append(stack)
                dealt += stack.damage_per_second * dt
            # 掉完的层从表里摘掉。层数就是列表长度（见 Ball.venom_stacks），
            # 不摘的话技能2 会按一个虚高的层数结算
            ball.venom = kept or None
            if dealt <= 0.0:
                continue
            ball.take_damage(dealt)
            self.effects.drain_damage(ball.player, ball.position, dealt)
        self.judge()

    def venom_burst(self, caster: Ball, target: Ball, damage: float,
                    heal: float) -> None:
        """毒发：伤对方这么多，回自己这么多。数值由技能算好，这里只管执行。

        和 NightfallSkill 调 start_darkness 是同一个分工：技能管数值，执行
        留在 Match——它是唯一摸得到 effects 的地方。

        这一下的环炸在**中毒的人身上**，不在两人中间（见 Hit.at）：毒是从他
        自己身体里发出来的，不是一颗从对面飞过来的东西。所以两颗球隔着半场
        也照样"炸在他身上"。
        """
        target.take_damage(damage)
        self.effects.hits.strike(Hit.at(target.position, target, damage))
        # 回血报**实际**回的量：满血时这一下回的是 0，飘个绿字就是假数字
        healed = caster.heal(heal)
        if healed > 0.0:
            self.effects.heal(caster.player, caster.position, healed)
        self.judge()

    # ---------------- 望的棋盘 ----------------
    def sync_go_board(self) -> None:
        """让棋盘和场上的人对上：有望就有棋盘，一个望都没有就没有，重开就清空。

        和 NightfallSkill 调 start_darkness 是同一个分工：技能管数值，需要场地
        的那一步留给 Match——格子的边长要从**战场边长**算出来，球不知道战场在哪。

        这件事必须在阵容定下来之后做，所以它挂在 reset_outcome 的最后（那里是
        每次选人、重开都会走到的地方），而不是望出生的时候：pick 是一个一个来的，
        刚出生的那一个不知道自己是不是场上的**唯一**一个望，也不知道另一个位置
        待会儿会不会也换成望。

        **棋盘是共用的一块**：两个望对打时格子只有一套，两边各挂各的落子节奏
        （球上的 go_plan），所以子会多一倍，但格子不会变成两层——两层的话两颗子
        会落进同一格，画面上叠在一起，判定也不知道该算谁的。

        重开时**只清子、不重铺**：几何（size / cell / origin）是跟着战场走的，
        战场没变它就一模一样，重铺没有意义。真正要清的只有那些子——它们的 owner
        是上一局的玩家序号，留着会变成没人认领的雷。
        """
        if not any(ball.go_plan is not None for ball in self.combatants()):
            self.go_board = None
            return
        if self.go_board is None:
            rect = self.arena.rect
            self.go_board = GoBoard(
                size=GO_BOARD_SIZE,
                cell=rect.width / GO_BOARD_SIZE,
                origin=Vector2(rect.topleft),
            )
            return
        self.go_board.stones.clear()

    def apply_go(self, dt: float) -> None:
        """结算棋盘：推进落子的钟，然后看这一帧谁踩到了子。

        和光环、激光、蛛丝、毒刺同一批结算，都放在吸住/钩锁的提前返回之前——
        被吸住、被钩着拖着的人也照样会踩到子：子画在地上，跟谁在动没关系。

        **一拍只落一颗子**（见 GoBoard.play）：钟到点了就落那一颗，是黑是白由
        那一手排到哪儿了决定。所以这里看到的是"每 interval 秒场上多一颗"，
        不是"每 interval 秒多一手棋"。

        **自己的子不炸自己**（同激光、蛛丝、毒刺），而且踩上去也**不消耗**它
        ——子只对对手有效，自己的球从上面走过去不会替对手把雷排掉。所以摘除
        排在所有权判定**后面**，顺序反过来就成了"自己走一趟替对手清场"。

        一帧最多踩中一颗：球心只落在一格里，一格最多一颗子。踩到的子当场摘掉
        （用户定的"踩过就消失"），它是地雷不是墙。

        落子和踩子是同一帧里的一前一后，所以**刚落到脚下的那一颗当帧就算数**
        ——对手正好站在那一格上时会被当场炸到，这是对的：子落在他头上。
        """
        board = self.go_board
        if board is None:
            return

        for owner in self.combatants():
            plan = owner.go_plan
            if plan is None or not owner.alive:
                continue
            if plan.tick(dt):
                board.play(plan, owner)

        for ball in self.combatants():
            if not ball.alive:
                continue
            cell = board.cell_of(ball.position)
            if cell is None:
                continue
            stone = board.stone_at(cell)
            # 按**边**比，不按球比：望自己召出来的东西踩上去也算自己一边
            if stone is None or self.same_side(stone.owner, ball):
                continue
            board.take(cell)
            ball.take_damage(stone.damage)
            ball.apply_slow(stone.slow_seconds, stone.slow_ratio)
            # 圈炸在**格心**上，不是炸在球身上（见 Hit.at）：踩的是地上那一格，
            # 不是自己身上。速度取受害者自己的——它是自己走上去的
            self.effects.hits.strike(Hit.at(
                board.center_of(cell), ball, stone.damage, speed=ball.speed,
            ))
        self.judge()

    def apply_slows(self, dt: float) -> None:
        """结算带时长的减速（踩到棋子）：还慢着的，压低这一帧的速度。

        走的是和光环、蛛丝**同一个出口**（ball.speed_scale 取 min），区别只在
        它自己带倒计时：踩一下是"已经发生过的事件"，人跑开了也该继续慢一会儿；
        光环是"此刻站在圈里"，走出圈下一帧就恢复。

        所以它必须在这里、在 reset_speed_scale 之后打上去，而且**每帧**都打：
        单靠踩中的那一帧设一次是没用的，下一帧开头就被抹回 1.0 了。

        取 min 而不是乘：减速**不叠加**（用户定的），和蛛丝那几根同一个处理。
        真乘起来的话，连踩两颗就贴在地上了。
        """
        for ball in self.combatants():
            slow = ball.slow
            if slow is None:
                continue
            # 先打上去再倒计时：这一帧已经生效了才算它过期。反过来写的话，
            # 踩中的那一下会少吃一帧的减速
            ball.speed_scale = min(ball.speed_scale, 1.0 - slow.ratio)
            slow.remaining -= dt
            if slow.remaining <= 0.0:
                ball.slow = None

    # ---------------- 穿刺 ----------------
    def update_thrusts(self, dt: float) -> None:
        """推进场上所有正在冲的穿刺：沿锁死的方向走一步，可能打中，可能撞墙。

        冲的这几帧球不按自己的动量走，所以它和钩锁一样要在 Match 里单独推。
        """
        for ball in self.combatants():
            thrust = ball.thrust
            if thrust is None:
                continue
            if not ball.alive:
                ball.thrust = None
                continue

            step = min(thrust.speed * dt, thrust.remaining)
            # 撞墙就停：这一步最多走到墙跟前，多出来的那点不补、也不反弹
            limit = self.arena.travel_limit(ball.position, thrust.direction, ball.radius)
            blocked = limit <= step
            step = min(step, limit)

            ball.position += thrust.direction * step
            thrust.remaining -= step
            landed = self.check_thrust_hit(ball, thrust)
            if self.finished:
                return
            if landed or thrust.finished or blocked:
                self.finish_thrust(ball)

    def check_thrust_hit(self, ball: Ball, thrust) -> bool:
        """冲的过程中，够不够得着对方。够着了就捅这一下，返回 True。

        判的是**距离**（球面挨上），不是"方向对不对"：方向出手时就锁死了，
        敌人要是让开了，这一路冲过去两者最近也隔着一段，够不着就是够不着。
        所以这一问同时管住了两种躲法——横向让开、站得比冲的距离还远。

        一次穿刺只打一下，打出去就把 landed 立起来。

        **捅中就停在对方身前**，不接着往那个方向冲完。这一步必须做：一帧要走
        三十来像素，够着的那一刻球已经扎进对方身体里了，不收回来就会留下一对
        重叠的球，而下一帧的碰撞结算会把出手时那份速度整个换给对方（等质量
        弹性碰撞，正撞是全额转移）——一次成功的穿刺反而把自己冲停在原地。
        摆到正好相切的位置，既看得见"刀尖顶到人了"，又不给碰撞留机会。
        """
        if thrust.landed:
            return False
        for target in self.combatants():
            if self.same_side(ball, target) or not target.alive:
                continue
            reach = ball.radius + target.radius
            offset = target.position - ball.position
            if offset.length() > reach:
                continue
            thrust.landed = True
            ball.position.update(target.position - thrust.direction * reach)
            target.take_damage(thrust.damage)
            self.effects.hits.strike(Hit.on(
                ball, target, thrust.damage, speed=thrust.speed,
            ))
            self.judge()
            return True
        return False

    def finish_thrust(self, ball: Ball) -> None:
        """冲完了：收起穿刺状态，按出手时记下的那份速度接着往这个方向走。

        走 set_effective_velocity 而不是直接写 velocity——那份速度是"实际速度"
        口径（含加速、含减速折扣），直接写会把加速算两遍。
        """
        thrust = ball.thrust
        ball.thrust = None
        ball.set_effective_velocity(thrust.direction * thrust.exit_speed)

    def direction_to_opponent(self, ball: Ball) -> Vector2:
        """从这颗球指向对面那颗的单位向量。刚好重合时退回自己的朝向。

        只认**对方本人那颗主球**，不看骑士。瞄准是"我要冲谁"这个层面的决定，
        而骑士是挡在路上的东西、不是目标——对着骑士放穿刺或闪现没有意义。
        技能一律冲着对方本人去，骑士要挡就靠自己的身板去挡（穿刺途中撞上骑士
        照样捅得到，见 check_thrust_hit）。
        """
        other = self.opponent(ball)
        if other is not None and other.alive:
            offset = other.position - ball.position
            if offset.length_squared() > 1e-12:
                return offset.normalize()
        return Vector2(ball.heading)

    # ---------------- 碰撞 ----------------
    def resolve_collisions(self) -> None:
        """场上一对一对地结账。**所有球走同一条路**。

        原来分两趟：主球对一趟（resolve_collision），带召唤物的那些对另一趟
        （resolve_summons_collisions）。那个分法是被"两颗主球"逼出来的——主球
        那一趟从头到尾把两球解包成 first/second（问钩锁有没有拽着这一对、问
        霸体、要抓就把这一对绑起来），多一颗球就进不去。

        分裂一来，"一个玩家好几颗球"成了常态，主球那一趟自己也解不了包了。
        于是合成一条通用的路：**每一对都问一遍角色**，能发生什么由主张决定，
        而不是由"这颗球是主球还是召唤物"决定。原来那些分野随之消失——骑士能
        被抓吗？能，但骑士的主张里没有 grab，所以不会发生；召唤物是霸体吗？
        不是，所以它照样推得动。规矩一条没改，只是不再靠名单提前切断。

        三条规矩原样保留：

        - **同边只撞不伤**：不问主张就不会有伤害、抓取、沉默（Character.
          same_side_collisions 是唯一那个开口的特例，分裂要用）。
        - **抓取照常**：Latch 是"两球粘成一团"，谁想抓谁主张。
        - **每帧只挑"刚贴上"的那些对结算一次**，剩下的只做分离。一对一个
          标记，存的是两颗球的 uid（见 Match.contacts）——主球时代整场只可能
          有一对、一个 bool 就够，现在球有好几颗，共用一个 bool 会让其中一对
          贴上时压制住其它所有对的结算。
        """
        units = self.combatants()
        contacts: set[tuple[int, int]] = set()
        for index, first in enumerate(units):
            for second in units[index + 1:]:
                if not (first.alive and second.alive):
                    continue
                offset = second.position - first.position
                minimum = first.radius + second.radius
                if offset.length_squared() >= minimum * minimum:
                    continue

                distance = offset.length()
                # 正重合时法线无从谈起，随便挑一个方向把它们推开
                normal = offset / distance if distance > 0 else Vector2(1.0, 0.0)
                key = (min(first.uid, second.uid), max(first.uid, second.uid))
                contacts.add(key)
                changed = self.bump(first, second, normal, distance, minimum,
                                    fresh=key not in self.contacts)
                if changed:
                    # 分裂或融合把场上的阵容换了：手上这份快照里还躺着已经被
                    # 换掉的那两颗球，接着往下走就是对着空气算账。清空接触名单、
                    # 这一帧到此为止——下一帧重新取快照、重新判"刚贴上"
                    self.contacts = set()
                    return

        # 整份名单换掉而不是往里加：这一帧没挨着的对，下一帧再贴上要重新算"刚贴上"
        self.contacts = contacts

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

    def forget_contact(self, first: Ball, second: Ball) -> None:
        """把这一对从"贴着"的名单里划掉。

        钩锁松手、吸住松口这两处要主动调：那一刻两球**仍然**是相切的（是被人
        摆成那样的），不划掉的话下一次真撞上会被当成"还贴着"而漏掉一整次伤害。
        名单本身每帧重算（见 resolve_collisions），所以正常分开的两球不用管。
        """
        self.contacts.discard(
            (min(first.uid, second.uid), max(first.uid, second.uid))
        )

    def bump(self, first: Ball, second: Ball, normal: Vector2, distance: float,
             minimum: float, fresh: bool) -> bool:
        """一对相撞。fresh 是"这一对是不是这一帧才贴上的"。

        返回 True 表示**这一撞把场上的阵容换了**（分裂或者融合）。调用方那一趟
        到此为止，理由写在 resolve_collisions 里。

        弹开走的是等质量弹性碰撞（沿法线的速度分量互换），没按半径算质量——
        更物理一点当然也可以（黑体上确实是按半径平方），但场上能推的球就只有
        主球和骑士那两种量级，按半径算的差别肉眼看不出来，而"两边写着同一套"
        是有价值的：霸体的处理、分离的处理、抓取的处理全都只写一遍。
        """
        # 钩锁正拽着这一对、或者有人正穿刺：这一对不算碰撞。拖的时候不算，是
        # 免得拖到身前那一瞬间先互撞一下白扣一次血；冲的时候不算，是"穿刺这一下
        # 由穿刺自己结算"——伤害、停在哪，都在 update_thrusts 里定好了，碰撞
        # 再来插一脚就是重复结算。位置正由别人摆着，所以连分离都不做
        if self._is_pulled_pair(first, second) or first.thrust or second.thrust:
            return False

        same = self.same_side(first, second)
        wants = None
        if fresh:
            # 同边一概不问主张（"自己人只撞不伤"，见 resolve_collisions）。
            # 除非角色自己开口要——分裂那条"自己跟自己相撞就合体"本来就只有
            # 同边才可能发生，不问就永远不会发生（Character.same_side_collisions）
            if not same or first.character.same_side_collisions \
                    or second.character.same_side_collisions:
                wants = (
                    first.character.on_collision(first, second),
                    second.character.on_collision(second, first),
                )

        if wants is not None:
            first_wants, second_wants = wants
            # 撞击伤害只要撞上就结算。抓取只顶替"弹开"，不免除伤害——所以被抓住
            # 的一方在被抓住的那一瞬间仍然打得出这一下。**同边不结算伤害**：
            # 主张是问了（分裂要），但规矩没变
            if not same:
                #
                # 每一方身上落**两笔**：对方主张打过来的那一笔，和自己主张里
                # "自损"的那一笔（国王就是靠后者变成"撞上去是亏的"）。两笔都是
                # 各自算好的数，这里只管往下砸
                second.take_damage(first_wants.damage_to_other)
                first.take_damage(first_wants.damage_to_self)
                first.take_damage(second_wants.damage_to_other)
                second.take_damage(second_wants.damage_to_self)
                # 撞得有多快取**相对速度**：两球各自多快不重要，合起来撞得狠不狠
                # 才重要，所以迎面对冲能撞出最大那一下。这一下也是全场唯一会顿帧
                # 的命中。飘的数字是每一方这一撞总共掉了多少，两笔加在一起——
                # 不然国王那一边只飘出"对方打来的 20"，血条却掉了 65
                self.effects.hits.strike(Hit.between(
                    first, second,
                    first_takes=second_wants.damage_to_other
                    + first_wants.damage_to_self,
                    second_takes=first_wants.damage_to_other
                    + second_wants.damage_to_self,
                    speed=(first.effective_velocity - second.effective_velocity).length(),
                ))

            # 阵容先动，再判胜负：分裂和融合都发生在这一撞上，而且都会把伤害
            # 结算留下来的那颗球换下去（融合是把两块并成一块，其中一块没了）
            if first_wants.fuses or second_wants.fuses:
                self.fuse_balls(first, second)
                return True
            if first_wants.splits or second_wants.splits:
                self.split_pair(first, second, first_wants.splits, second_wants.splits)
                return True

            self.judge()
            if self.finished:
                # 有人被这一下打死了，弹开还是吸住都不必再谈
                self.separate(first, second, normal, distance, minimum)
                return False

        # 抓取：不弹开，改成粘住持续吸取。排在霸体**前面**——霸体挡的是"被推动"，
        # 不是"被碰上"：抓取本身照常发生，只是抓到手之后两边都动不了
        # （见 combined_velocity：推不动的一方等效无穷大质量，合体速度由它说了算）。
        # 同边不会走到这里：同边主张里那几个开关一概不作数（自己人抓自己人干什么）
        if wants is not None and not same and (first_wants.grabs or second_wants.grabs):
            grabber, victim, wanted = (
                (first, second, first_wants) if first_wants.grabs
                else (second, first, second_wants)
            )
            # 先摆到刚好相切，吸住期间就保持这个姿势。霸体的一方不让路，
            # 所以这一步的位移全由抓人的一方走完
            self.separate(first, second, normal, distance, minimum)
            self.start_latch(grabber, victim, wanted.grab_seconds,
                             wanted.grab_drain_per_second, silences=wanted.silences)
            return False

        # 霸体：定住的一方推不动，撞上来的一方原路弹回。
        # 走到这里说明没人想抓（谁都抓的话上面那条就返回了），所以这是
        # "普通撞击撞上霸体"的情形
        if first.frozen or second.frozen:
            self.reflect_off(first, second, normal, distance, minimum)
            return False

        # 走到这里说明双方都不抓。此时 silences 一概不生效——沉默没有时长，
        # 必须有人负责解封，而"撞一下"这件事本身没有结束时刻，封了就没人解得开。
        # 所以从碰撞来的沉默只跟抓取配着用（绑多久就封多久）。想只封不绑，
        # 只能由技能来给：技能有生命周期，能在该结束的时候自己 unsilence。

        # 等质量弹性碰撞：沿法线的速度分量互换。
        # 先把两个速度取出来再写回，否则第二行算的是已经被改过的 first。
        # **霸体的一方不参与换速度**：它的速度不由自己说了算，换了也白换
        # （吸住的一对就是这样，两球本来就是一整团在飞）
        if not (self.has_super_armor(first) or self.has_super_armor(second)):
            first_velocity = first.effective_velocity
            second_velocity = second.effective_velocity
            first.set_effective_velocity(
                first_velocity - (first_velocity - second_velocity).dot(normal) * normal
            )
            second.set_effective_velocity(
                second_velocity - (second_velocity - first_velocity).dot(normal) * normal
            )

        # 自己人相撞**什么都不报**：不飘字、不炸圈、不顿帧。这个游戏里"震"的
        # 含义是"挨了一下"（见 fx/impact.py），而这一下谁都没挨着。国王冲进自己
        # 那群骑士里的时候，每蹭一下都顿一帧会难看得没法玩
        self.separate(first, second, normal, distance, minimum)
        return False

    # ---------------- 分裂 ----------------
    def split_pair(self, first: Ball, second: Ball,
                   first_splits: bool, second_splits: bool) -> None:
        """一边或两边同时裂开。

        两边一起裂是可能的（两个分裂撞上了），各裂各的：朝**远离对方**的方向
        散开是用户定的，所以两边散的方向正好相反。

        方向在两边都还是原样的时候**一次算好**：先裂 first 会把它的位置挪走，
        再拿它去算 second 往哪儿散，第二颗散的就是照着半身的落点算出来的方向。
        """
        offset = second.position - first.position
        if offset.length_squared() > 1e-12:
            first_away = -offset.normalize()
        else:
            # 正好重合，方向无从谈起，退回自己的朝向
            first_away = Vector2(first.heading)
        if first_splits:
            self.split_ball(first, first_away, first.character.split_speed)
        if second_splits:
            self.split_ball(second, -first_away, second.character.split_speed)

    def split_ball(self, ball: Ball, away: Vector2, speed: float) -> Ball:
        """把球裂成两半：手上这颗留下当其中一半，另造一颗新的当另一半。

        为什么**留下原来那一颗**而不是两颗都新造：球是实体，场上指向它的地方
        认的是对象本身（血条挑的代表、钩锁的目标、"这一对里有没有它"）。让
        原来那颗接着当"这一边的那块球"，只把它的尺寸、上限、代数改小，最省事
        也最不容易漏一处引用。

        两半各自**减半**血量和大小（用户定的），于是总量一个数都没少——一块
        500 血的裂成两块 250 的，玩家那边的总血量原样。代价藏在别处：每一块
        都比原来小、比原来脆，撞人时的质量口径（半径的平方）掉到四分之一。

        散开的方向由调用方给（用户定的"朝远离来袭者的方向散开"），这里只负责
        把它掰成左右两叉，两个半身各自沿着自己那一叉飞出去。
        """
        ball.generation += 1
        ball.hp *= 0.5
        ball.size = ball.character.radius * 0.5 ** ball.generation
        ball.max_hp = ball.character.max_hp * 0.5 ** ball.generation

        twin = Ball.spawn(
            ball.player, ball.character, Vector2(ball.position),
            velocity=Vector2(ball.velocity),
            hp=ball.hp, size=ball.size, max_hp=ball.max_hp,
            generation=ball.generation,
        )
        # 加速和冷却跟着走：半身是同一颗球劈出来的，两份"攒下来的本钱"当然
        # 一人一半地接着算，而不是让新的那一块从零开始（spawn_speed 尤其要抄，
        # 它是加速的标尺，两份不一样的话两块半身会越差越远）
        twin.spawn_speed = ball.spawn_speed
        twin.boost_stacks = ball.boost_stacks
        twin.boost_bonus = ball.boost_bonus
        twin.cooldown_timer = ball.cooldown_timer

        origin = Vector2(ball.position)
        # 摆开的距离按**新的半径**算：两个半身要摆到互不相切之外，还得离来袭者
        # 足够远——碰撞结算就发生在这一帧，摆得太近的话下一帧它们各自又贴着敌人
        # 一次，一发撞击能连打出三笔伤害
        spread = SPLIT_SPREAD_ANGLE
        step = ball.size * 2.0 + SPLIT_SPAWN_GAP
        for sign, target in ((1.0, ball), (-1.0, twin)):
            direction = away.rotate_rad(sign * spread)
            target.position.update(origin + direction * step)
            target.set_effective_velocity(direction * speed)
            self.arena.clamp_inside(target.position, target.radius)
            # 两半的融合锁：不锁的话下一帧它们就贴在相切的位置上（本来就这么摆的），
            # 当场融回原样，分裂等于没发生过
            target.fuse_lock = FUSE_LOCK_SECONDS

        ball.character.attach_passives(twin, self)
        self.units.append(twin)
        # 刚劈出来的两块：这一撞里它们和敌人有没有贴上都还没算过，所以名单里
        # 不预先写"贴着"。下一帧从干净的状态重新判
        return twin

    def fuse_balls(self, first: Ball, second: Ball) -> None:
        """自己撞自己：两块**同代**的半身合回一块，退一代。

        "退一代"（用户定的）是这条机制的关键：gen2 + gen2 合出来的是 gen1，
        尺寸血量都翻一倍，**而且又能再裂两次**。所以融合不是白合——它是这个
        角色唯一能把"裂散了"收回来、重新攒出一块大身板的手段。至于"分裂两次
        的和分裂三次的碰撞没效果"，那一条不在这个函数里：能不能合是角色在
        on_collision 里判的（代数不等就什么都不提），Match 只执行结果。

        合出来的那一块继承 first 这个对象，second 从场上摘掉（同 split_ball
        里"留下原来那一颗"的道理）。

        血量**相加**、速度取动量守恒的合体速度：融合不凭空造出东西，只是把两份
        并回一份。所以一块残血的半身和一块满血的半身合回来，得到的既不是满血
        也不是残血，而是它们两个加起来那么多。
        """
        first.generation -= 1
        first.size = first.character.radius * 0.5 ** first.generation
        first.max_hp = first.character.max_hp * 0.5 ** first.generation
        first.hp = min(first.max_hp, first.hp + second.hp)
        first.position.update((first.position + second.position) / 2)
        # 动量守恒：按半径平方加权，和吸住的合体速度是同一套算法
        first.set_effective_velocity(self.combined_velocity(first, second))

        self.units = [ball for ball in self.units if ball is not second]
        # 合出来的这一块也上锁：旁边可能还站着一块同代的（另一对拆出来的），
        # 不锁的话下一帧"啪"地又合一次，一代一瞬间退到底，四块碎片眨眼并成一块
        first.fuse_lock = FUSE_LOCK_SECONDS

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
            grabber=grabber,
            victim=victim,
            velocity=self.combined_velocity(grabber, victim),
            remaining=seconds,
            drain_per_second=drain_per_second,
            silences=silences,
        )
        # 咬合的那一下额外震一份。抓取本来就是从一次碰撞开始的（上面已经震过
        # 一次了），这一份是"咬上了"比"撞一下"更重的那点差别
        self.effects.hits.jolt(SHAKE_EXTRA_BITE)

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
        grabber = latch.grabber
        victim = latch.victim
        latch.velocity, impact = self.arena.bounce_rigid_pair(
            grabber, victim, latch.velocity
        )
        if impact is not None:
            self.effects.bounce(impact, grabber.color, latch.velocity.length())

    def update_latch(self, dt: float) -> None:
        """吸住期间的每一帧：整体飞、持续吸取、到点松口。"""
        latch = self.latch
        grabber = latch.grabber
        victim = latch.victim

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
        grabber = latch.grabber
        victim = latch.victim

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
        # 松口时两球仍是相切的，清掉接触标记；否则下一次真正撞上会被当成"还贴着"而漏掉
        self.forget_contact(grabber, victim)

    def latch_pair(self) -> tuple[Ball, Ball] | None:
        """当前粘在一起的两球（没吸住则为 None），供调试视图画连线用。"""
        if self.latch is None:
            return None
        return self.latch.grabber, self.latch.victim

    def retire_summons(self) -> None:
        """把被打死的召唤物从场上摘走。

        骑士**只有被打死才消失**（用户定的）：没有存活时长、不会自己走，所以
        除了这里没有第二条退场的路。

        挂在 judge 上，是因为 judge 是"任何一处伤害结算完之后"的必经之路——
        每一次扣血（光环、激光、刀、锤、蛛丝、毒刺、中毒、棋子、穿刺、碰撞、
        吸住）后面都跟着一句 judge。放在这里就等于"谁死了谁下台"，不用在十几个
        扣血点各写一遍，也不会漏掉哪个新加的伤害源。

        摘的时候顺带清掉沾着它的接触标记：uid 永不复用，留着也认不错人，但那份
        名单会随着对局一直长下去。
        """
        live = self.summons()
        if len(live) == len(self.units) - len(self.mains()):
            # 数量和场上对得上，说明没有召唤物刚死，整趟都不用跑
            if not any(not unit.alive for unit in live):
                return
        gone = {unit.uid for unit in self.units if unit.summoned and not unit.alive}
        if not gone:
            return
        self.units = [unit for unit in self.units if unit.uid not in gone]
        self.contacts = {
            pair for pair in self.contacts
            if pair[0] not in gone and pair[1] not in gone
        }

    # ---------------- 胜负 ----------------
    def judge(self) -> None:
        """胜负：**全灭算输**。

        原来数的是"两颗主球还剩几颗活着"——一个玩家就一颗球，所以"活着的不齐"
        就等于"有人没了"。分裂一来，一个玩家在场上是**好几块**（最多八块），
        "哪一块死了"不再是"这个人死了"，所以判的是**哪一边一块都不剩了**
        （用户定的，顺带也定了"算总血量"，那个数在 side_hp 里）。
        """
        # 先收尸再判胜负：骑士死光不等于谁输了，这一句和下面的判定没有关系。
        # 放在这里只是因为它是"伤害结算完"的必经之路，见 retire_summons
        self.retire_summons()
        # 死掉的块**不从 mains 里摘**（它们还躺在地上当尸体、界面也可能还在画），
        # 所以"有哪些玩家"是稳定的，掉的是"哪些玩家还有活口"
        sides = {ball.player for ball in self.mains()}
        alive_sides = {ball.player for ball in self.mains() if ball.alive}
        if alive_sides == sides:
            return
        self.finished = True
        # 同时全灭则平局。赢家报的是**玩家序号**——胜负是玩家之间的事，
        # 界面等着这个数去点亮哪一边
        self.winner = next(iter(alive_sides)) if len(alive_sides) == 1 else None
