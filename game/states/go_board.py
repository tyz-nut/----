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
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from pygame.math import Vector2

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
    """

    cell: tuple[int, int]   # 落在第几列、第几行（从 0 开始）
    color: str              # BLACK / WHITE
    owner: int              # 落下它的玩家序号。自己的子不炸自己
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

    def place(self, plan: GoPlan, owner: int) -> None:
        """落一手：先黑后白，白子挨着刚落的黑子。

        规则（用户定的）：

        - 黑子随机落在**任意一个空格**上。
        - 白子落在**刚落的这颗黑子**上下左右四格之一。
        - 四邻都占着、或者黑子落在边角上没那么多邻格时，**这一轮就不下白子**
          ——所以棋盘越满，白子越少，黑子（伤害高的那种）占比自然越来越高。
          这不是补丁，是这一条规则自己长出来的节奏。

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

        # 邻格里**还没被占的**那些。白子不下在已有子上，也不下在黑子自己那格
        # （neighbors 本来就不含自己）
        open_neighbors = [
            cell for cell in self.neighbors(black_cell)
            if self.stone_at(cell) is None
        ]
        if not open_neighbors:
            return
        self.stones.append(GoStone(
            cell=random.choice(open_neighbors),
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

    timer 是**离下一手还有几秒**，从 interval 往下走。不记"已经过了多久"：
    条上画的是"还有多久"，玩家要判断的是"我现在冲过去会不会正好赶上落子"。
    """

    interval: float         # 每隔几秒落一手
    black_damage: float     # 黑子踩上去掉多少血
    white_damage: float     # 白子踩上去掉多少血（比黑子轻）
    slow_seconds: float     # 踩到减速多久（黑白一样）
    slow_ratio: float       # 减速比例（黑白一样）
    timer: float = 0.0      # 离下一手还有几秒

    def tick(self, dt: float) -> bool:
        """走一步钟，返回**这一帧该不该落一手**。

        落完之后钟要重新拧满，而且必须是"赋值"而不是"加上一个 interval"：
        一帧 dt 有可能比 interval 还大（卡顿之后主循环把它截断在 MAX_FRAME_TIME，
        也就是 0.25 秒），累加的话那 0.25 秒会被算成好几手，一帧之内啪地落满
        半个棋盘。赋值等于"欠下的那点不要了"，最多晚一帧，不会多落。
        """
        self.timer -= dt
        if self.timer > 0.0:
            return False
        self.timer = self.interval
        return True
