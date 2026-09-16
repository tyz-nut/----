"""渔夫的钩锁。

一个会弹墙的投掷物，加上"钩中人之后沿原路把对方拖回来"那条折线。

和 ball.py 里的 Aura 一样，这个类只是**状态**：怎么飞、拉谁、拉多快，
由 Match 每帧按这里记的东西去算。它自己不持有对 Ball / Match 的引用，
免得又绕成循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pygame.math import Vector2

if TYPE_CHECKING:
    # 只在类型检查时 import：ball.py 在运行时是 import 这个模块的（Ball 上挂着
    # hook 这一栏），真 import 进来就绕成一个圈了
    from ..core.ball import Ball


def polyline_length(path: list[Vector2]) -> float:
    """折线总长。"""
    return sum(
        (path[index + 1] - path[index]).length() for index in range(len(path) - 1)
    )


def visible_path(path: list[Vector2], pulled: float) -> list[Vector2]:
    """折线上**还剩在外面**的那一段：从起点一直画到"离末端 pulled 像素"处。

    pulled = 0 就是整条（还没开始收）。收线时钩尖一路往回走，绳子要跟着一起
    短——只用 point_from_end 挪钩尖是不够的，那样线还画着原来的全长，看着像
    一条绳子自己往回缩、而钩子挂在原地不动（用户报的就是这个）。

    从末端往回量，和 point_from_end 是同一个方向：收线本来就是倒着走这条路的。
    """
    total = polyline_length(path)
    cut = total - pulled
    if cut <= 0.0 or not path:
        return []
    if len(path) == 1:
        return [Vector2(path[0])]

    points = [Vector2(path[0])]
    walked = 0.0
    for index in range(1, len(path)):
        start, end = path[index - 1], path[index]
        segment = (end - start).length()
        if segment <= 1e-9:
            continue
        if walked + segment >= cut:
            # 这一段被截断了：只画到 cut 那一点
            points.append(start + (end - start) * ((cut - walked) / segment))
            return points
        points.append(Vector2(end))
        walked += segment
    return points


def point_from_end(path: list[Vector2], distance: float) -> Vector2:
    """折线上**从末端往回数** distance 像素的那个点。

    收线是倒着走这条路的，所以量法也是倒着的：distance = 0 就是钩中的位置
    （path 末端），distance = 总长就是折线起点（渔夫身前）。

    每帧重新走一遍折线，不做增量游标——折线点数就是钩锁弹了几次墙，通常个位数，
    为这点开销多存一份状态不划算。
    """
    if not path:
        return Vector2()
    if len(path) == 1 or distance <= 0.0:
        return Vector2(path[-1])

    remaining = distance
    for index in range(len(path) - 1, 0, -1):
        end, start = path[index], path[index - 1]
        segment = start - end                 # 从末端往回走，所以是反过来减
        length = segment.length()
        last = index == 1
        if length <= 1e-9:
            if last:
                return Vector2(start)
            continue
        if remaining <= length or last:
            return end + segment * min(1.0, remaining / length)
        remaining -= length
    return Vector2(path[0])


@dataclass(frozen=True)
class FishSpec:
    """钩空之后那条鱼怎么长、怎么游、放不放得出来。

    单独一个类而不是七个字段摊在 Hook 上：这一组数在放钩的那一刻整份抄下来，
    之后一路只读，所以打包成不可变的一小份最省事——Hook 上多一个字段，
    cast_hook 的入参和调用方就都短一截。

    体型在 [min_size, max_size] 之间**均匀**随机，伤害和持续时间都正比于体型
    （用户定的"根据大小造成伤害与持续时间"），所以只需要两个比例，不需要再给
    伤害和时长各配一套上下限。
    """

    min_size: float = 9.0             # 体型下限（像素半径）
    max_size: float = 24.0            # 体型上限
    damage_per_size: float = 3.0      # 每 1 像素体型咬多少血
    duration_per_size: float = 0.12   # 每 1 像素体型活多少秒
    speed: float = 480.0              # 直线游速（像素/秒）
    turn_rate: float = 4.2            # 每秒最多转多少弧度，决定它绕不绕得过急弯
    # 满舵转弯时掉多少速（0.86 = 只剩一成四）。**这个不是手感参数**：它决定这条鱼
    # 的转弯半径 speed×(1-turn_slow)/turn_rate，那个半径必须小于咬合距离
    # （鱼半径 + 敌人半径），否则鱼会绕着敌人画圈、一辈子咬不着（见 Fish.steer）
    #
    # 所以它和 speed 是一对、得一起调：speed 涨多少，这里的转弯半径就跟着涨多少。
    # 当前 480×0.14÷4.2 ≈ 16 像素，最小的一档咬合距离是 21（小鱼 r9 + 骑士 r12）
    turn_slow: float = 0.86
    fail_chance: float = 0.3          # 钩空之后连鱼都召唤不出来的概率


@dataclass
class Hook:
    """一条甩出去的钩锁。

    两个阶段，由 target 区分：

    - **target is None：还在飞。** position / velocity 是它自己的运动状态，
      path 是出膛以来走过的折线——path[0] 是出膛点，中间每个点是弹墙的拐角
      （正好落在墙面上），末端跟着钩尖走。
    - **target 有值：钩中了，正在收线。** 这时位置不再由速度决定，改成由
      path + pulled 决定——**钩锁往回走的是它当初飞出去的那条路**，所以敌人
      是被沿着它撞过的每一个墙角原样拖回来的，不是抄近路走直线。

    收线开始时会往 path 的**开头**插一个终点（渔夫身前）。放在开头而不是末尾，
    是为了让"从末端往回数"这条路自然地在渔夫面前停下，也让画绳子时
    [渔夫] + path 正好是一条从渔夫连到钩尖的折线。
    """

    position: Vector2
    velocity: Vector2
    path: list[Vector2] = field(default_factory=list)
    # 技能放出来时抄下来的参数。和 Aura 一样，钩锁自己带着这一发的数值，
    # Match 就不用回头去问角色——角色改成什么样都不影响已经在飞的那一条
    pull_speed: float = 800.0       # 收线速度（像素/秒）
    drain_per_second: float = 30.0  # 收线期间每秒从敌人身上吸走多少血
    reel_gap: float = 8.0           # 拉到身前时两球之间留的空隙
    # 鱼线总共多长（像素）。**折线总长**，不是直线距离——弹了三次墙就是三段
    # 加起来。走到头还没钩到人就收场（见 Match.hook_missed）：鱼线是有限长的，
    # 甩不出去就是甩不出去。这个数比战场的对角线还长（600×600 的场，对角线
    # 约 849），所以现在等于"想去哪就去哪"，弹几次墙总能到
    max_length: float = 900.0
    # 钩空之后那条鱼的参数。抄在钩锁上而不是回头问角色：钩锁可能飞好几秒，
    # 这几秒里角色参数被改了（用户调数值就是这样），天上那条得按放出去时的规矩走
    fish_spec: FishSpec = field(default_factory=lambda: FishSpec())
    target: Ball | None = None      # 钩中的那一颗球；None = 还在飞
    pulled: float = 0.0             # 收线已经拉回来多少像素
    total: float = 0.0              # 收线全程多少像素（钩中时才定得下来）

    @property
    def reeling(self) -> bool:
        """钩中了、正在往回拖。"""
        return self.target is not None

    @property
    def pull_progress(self) -> float:
        """收线进度 0~1，画技能条用。"""
        return min(1.0, self.pulled / self.total) if self.total > 1e-9 else 1.0
