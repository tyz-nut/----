"""望的棋盘：战场被划成方格，格子上落着黑白棋子。

两样东西放在一个模块里，因为它们一个是**场地**、一个是**场地上的东西**，
而这两样的归属完全不同，这一点决定了各自写法的差别：

- GoBoard 是**整块棋盘**，属于 Match 而不是某一颗球（见 Match.go_board）。
  棋盘是"战场被划成什么样"，那是场地的属性——两个望对打时共用同一套格子。
  要是每个望各拿一块棋盘，两颗子会落进同一格，画面上叠在一起，判定也不知道
  该算谁的。
- GoPlan 是**这颗望的落子节奏**，属于球（见 Ball.go_plan）。它只有倒计时和
  数值，没有"子在哪"——子落在共享的那块棋盘上，每一颗都带着自己的 owner。
  两个望各走各的钟，所以对打时场上的子会多一倍，而格子不会。

## 棋子是地雷，不是墙

踩上去的子**就没了**（用户定的"踩过就消失"）。这一条把它和场上另外三样
"留在场上的东西"彻底分开了：

- 激光、蛛丝、毒刺都是**永久不封顶**的：越打越多，那是那三个角色的成长曲线。
- 棋子是**一直在流**的：落一手、被踩掉、再落一手，棋盘始终保持半空。

所以望的压力不来自"攒了多少"，来自**落子的节奏**——间隔越短，对手每一步
越容易踩上。

## 一手是一串

黑子和它的四颗白子不是同时出现的：黑子先落，四颗白子以**短得多**的间隔一颗接
一颗跟上，落完才进冷却（用户定的）：

    黑 ─0.2s─ 白 ─0.2s─ 白 ─0.2s─ 白 ─0.2s─ 白 ──[冷却]── 黑 ...

所以两次"间隔"不是同一个数：白子之间是 white_interval，四颗落完之后才隔
interval 起下一手。白子的格子因此在**黑子落地那一刻**就定下来、存在
GoPlan.pending 里等着一颗一颗兑现（见 GoBoard.play）——隔了哪怕几帧再算，也
算不出"当初挨着它的是哪四格"了。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pygame.math import Vector2

if TYPE_CHECKING:
    # 只在类型检查时 import：ball.py 在运行时是 import 这个模块的（Ball 上挂着
    # go_plan / go_board 这一路），真 import 进来就绕成一个圈了
    from ..core.ball import Ball

# 棋子的两种颜色。用字符串而不是 Enum：它只用来比相等（画成黑的还是白的）
# 和挑数值，没有别处要遍历或排序，和 arena 那四个墙名同一个理由
BLACK = "black"
WHITE = "white"


@dataclass
class GoStone:
    """棋盘上的一颗子。

    数值（伤害、减速）在**落下的那一刻**就烤在自己身上，和 WebAnchor / Spike
    一样：以后调技能参数不会把棋盘上已有的旧子一起改掉。

    owner 是**谁落的**，不是"这颗子是黑的还是白的"：自己的子不炸自己
    （同激光、蛛丝、毒刺），所以每颗子都得记着找谁收账。黑白的区别只在
    damage 那个数上，已经烤进去了。

    owner 存的是**那一颗球**，不是玩家序号。"自己的子不炸自己"问的是**哪一边**
    （Match.same_side），所以比的是 owner.player —— 望自己召出来的东西（如果
    以后有）踩上去也算自己一边。存球而不是存序号，是因为落子的那一刻手里就有
    球，而序号回头还得再查一次；顺带也躲开了"序号在一场里只有两个值"这个坑。
    """

    cell: tuple[int, int]   # 落在第几列、第几行（从 0 开始）
    color: str              # BLACK / WHITE
    owner: Ball             # 落下它的那一颗球。自己的子不炸自己一边
    damage: float           # 踩到掉多少血
    slow_seconds: float     # 踩到减速多久
    slow_ratio: float       # 减速比例，0.4 就是速度打六折


@dataclass
class GoBoard:
    """整块棋盘：几何 + 场上所有的子。

    几何（size / cell / origin）在开局铺棋盘的时候定死，之后再也不变；变着的
    只有 stones。棋盘不关心是谁的钟在走——落子是 GoPlan 的事，这里只提供
    "哪一格是空的"和"把子放上去"。

    格子大小 = 战场边长 / size，所以棋盘和战场**严丝合缝**：战场一改，格子
    跟着改，不需要另外对账。size 由 config 的 GO_BOARD_SIZE 给（用户要求的
    "棋盘大小可以在设定里自由调整"）。
    """

    size: int               # 每边几格
    cell: float             # 一格多少像素
    origin: Vector2         # 棋盘左上角，也就是战场左上角
    stones: list[GoStone] = field(default_factory=list)

    def cell_of(self, position: Vector2) -> tuple[int, int] | None:
        """球心落在哪一格。出了棋盘就是 None。

        判定就是"球心在哪一格"，不是"球面挨到棋子"——棋子是**格子**上的东西，
        踩上去的意思是整个人站进那一格，所以球心进格就算，和球多大无关。
        球贴着墙时球心仍在场内（墙的判定留了一个半径），所以正常走不到 None
        那一支，留着是给"以后棋盘比战场小"留的口子。
        """
        column = int((position.x - self.origin.x) // self.cell)
        row = int((position.y - self.origin.y) // self.cell)
        if 0 <= column < self.size and 0 <= row < self.size:
            return column, row
        return None

    def center_of(self, cell: tuple[int, int]) -> Vector2:
        """某一格的正中心。棋子画在这儿，不是画在落子时球待的地方——
        子落在格子里，不是落在点上。"""
        column, row = cell
        return Vector2(
            self.origin.x + (column + 0.5) * self.cell,
            self.origin.y + (row + 0.5) * self.cell,
        )

    def stone_at(self, cell: tuple[int, int]) -> GoStone | None:
        """这一格上有没有子。一格最多一颗（place 只挑空格），所以找到就返回。"""
        for stone in self.stones:
            if stone.cell == cell:
                return stone
        return None

    def take(self, cell: tuple[int, int]) -> GoStone | None:
        """把这一格上的子摘走（踩到了）。没有子就是 None。

        摘而不是标记成"炸过了"：踩过就消失（用户定的），棋盘上不留痕迹。
        """
        stone = self.stone_at(cell)
        if stone is not None:
            self.stones.remove(stone)
        return stone

    def empty_cells(self) -> list[tuple[int, int]]:
        """所有空格。落子从这堆里挑。"""
        taken = {stone.cell for stone in self.stones}
        return [
            (column, row)
            for row in range(self.size)
            for column in range(self.size)
            if (column, row) not in taken
        ]

    def neighbors(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """上下左右四格。

        返回的是**列表**不是固定的四个：棋盘是有限的，边上的格子只有三个邻格、
        角上只有两个。把"出界"当成一种普通的"没有这一格"，调用方就不用再判一次。
        """
        column, row = cell
        around = (
            (column, row - 1), (column, row + 1),
            (column - 1, row), (column + 1, row),
        )
        return [
            (c, r) for c, r in around
            if 0 <= c < self.size and 0 <= r < self.size
        ]

    def play(self, plan: GoPlan, owner: Ball) -> None:
        """落**一颗**子——这一拍轮到谁就落谁。

        望的一手不是"啪一下五颗一起出现"：黑子先落，四颗白子随后**很快地一颗接
        一颗**跟上（用户定的），一颗落完才轮到下一颗：

            黑 ─0.2s─ 白 ─0.2s─ 白 ─0.2s─ 白 ─0.2s─ 白 ──[冷却]── 黑 ...

        所以"间隔"有两份：白子之间是 white_interval（很短，看起来是唰唰唰唰连
        着铺开的一圈），四颗落完之后才隔 interval 这个冷却起下一手。两份间隔都
        在 GoPlan 上，这里只负责落子，拧钟是 plan.arm 的事。

        白子的格子**在黑子落下的那一刻就定好了**（存进 plan.pending）：白子必须
        挨着这颗黑子，而黑子是这一刻落的，之后棋盘会变，再算就算不出"当初那四格"
        了。
        """
        if plan.pending:
            self.drop_white(plan.pending.pop(0), plan, owner)
        else:
            self.drop_black(plan, owner)
        # 落完之后按**剩下的队列**重新拧钟：还有白子没落就还是短间隔，空了就是
        # 这一手完了，转成长冷却
        plan.arm()

    def drop_black(self, plan: GoPlan, owner: Ball) -> None:
        """落黑子，顺手把它的四邻记成待落的四颗白子。

        黑子随机落在**任意一个空格**上；四邻里已经有子的那几格不进队列——白子
        不叠在子上面。边角上邻格本来就少，队列自然短，一颗都排不上就是"这一轮
        不下白子"。

        棋盘满了就什么都不做。这在实际对局里到不了（子被踩掉就腾出格子），
        只是"没有空格可挑"这件事总得有个交代，不然 random.choice 会当场炸。

        数值从 plan 上取，烤进每一颗子里（见 GoStone）。
        """
        empties = self.empty_cells()
        if not empties:
            return

        black_cell = random.choice(empties)
        self.stones.append(GoStone(
            cell=black_cell,
            color=BLACK,
            owner=owner,
            damage=plan.black_damage,
            slow_seconds=plan.slow_seconds,
            slow_ratio=plan.slow_ratio,
        ))

        # 四邻里**还没被占的**那些，一格一颗。neighbors 不含黑子自己那格，所以
        # 黑子不会被自己的白子盖掉
        plan.pending = [
            cell for cell in self.neighbors(black_cell)
            if self.stone_at(cell) is None
        ]

    def drop_white(self, cell: tuple[int, int], plan: GoPlan,
                   owner: Ball) -> None:
        """落一颗白子。格子是黑子落下时定好的，轮到它这一拍才真落下来。

        隔了几拍，那一格可能已经被别人占了（比如对面也是个望），那就跳过——
        白子不叠在子上面，和排进队列时是同一条规矩。
        """
        if self.stone_at(cell) is not None:
            return
        self.stones.append(GoStone(
            cell=cell,
            color=WHITE,
            owner=owner,
            damage=plan.white_damage,
            slow_seconds=plan.slow_seconds,
            slow_ratio=plan.slow_ratio,
        ))


@dataclass
class GoPlan:
    """这颗望的落子节奏：多久落一手、落出来的子是什么成色。

    和 Blade / Hammer 同类——**数值全部烤在这里**，由 GoSkill.on_spawn 在
    造球时装上，之后它自己一直在（没有冷却也不会被"放"）。

    它和那些"常驻被动"唯一的区别是**它自己会走钟**：刀和锤子只在自己被推进
    的时候转（Match 每帧推一下），而这个钟一到就要求落子。所以它是这几样里
    唯一一个"不看场上发生了什么，只因为时间到了就产生效果"的东西。

    timer 是**离下一颗子还有几秒**，从当前的 gap 往下走。不记"已经过了多久"：
    条上画的是"还有多久"，玩家要判断的是"我现在冲过去会不会正好赶上落子"。

    pending 是**这一手还没落完的白子格**（见 GoBoard.play）。它把"一手"从一个
    瞬间摊成了五拍：黑子落下时把四邻排进队列，之后每一拍弹出一格。所以它为空
    就等于"这一手落完了，下一颗该起新的一手（黑子）"——技能条上那个"下一颗是
    黑是白"就是看它空不空（见 app.go_display）。

    **两种间隔**（用户定的）：同一手里面白子和白子之间隔 white_interval（很短，
    四颗白子是"唰唰唰唰"连着落下来的），一手落完（最后一颗白子落地）之后才隔
    interval 这个**冷却**起下一手。所以一轮的长度是

        4 × white_interval + interval

    而不是 5 × interval。gap 记的就是**这一次**倒计时拧了多长——两种间隔交替
    出现，条上的进度得拿对应的那一份当分母才画得准。
    """

    interval: float         # 一手落完之后隔几秒起下一手（冷却）
    white_interval: float   # 同一手里白子之间隔几秒
    black_damage: float     # 黑子踩上去掉多少血
    white_damage: float     # 白子踩上去掉多少血（比黑子轻）
    slow_seconds: float     # 踩到减速多久（黑白一样）
    slow_ratio: float       # 减速比例（黑白一样）
    timer: float = 0.0      # 离下一颗子还有几秒
    gap: float = 0.0        # 这一次倒计时是从几秒开始拧的（画进度条用）
    pending: list[tuple[int, int]] = field(default_factory=list)   # 待落的白子格

    def arm(self) -> None:
        """按"下一颗是什么"把钟拧上。

        队列里还排着白子 -> 下一颗是白的，隔 white_interval；队列空了 -> 这一手
        落完了，隔 interval 起下一手。拧钟只在这一个地方做，因为"下一颗是黑是白"
        这件事只有队列知道（见 GoBoard.play），散在别处早晚会对不上。
        """
        self.gap = self.white_interval if self.pending else self.interval
        self.timer = self.gap

    def tick(self, dt: float) -> bool:
        """走一步钟，返回**这一帧该不该落一颗子**。

        拧钟必须是"赋值"而不是"加上一个 gap"：一帧 dt 有可能比 white_interval
        还大（卡顿之后主循环把它截断在 MAX_FRAME_TIME，也就是 0.25 秒，而白子
        之间只隔 0.2 秒），累加的话一帧能被算成好几拍，四颗白子会挤在一帧里
        同时冒出来。赋值等于"欠下的那点不要了"，最多晚一帧，不会多落。

        这里拧的那一次只是**预拧**（按落子之前的队列猜），真落了子之后
        GoBoard.play 会再拧一次——那时候队列已经变了，那一次才是准的。
        """
        self.timer -= dt
        if self.timer > 0.0:
            return False
        self.arm()
        return True
