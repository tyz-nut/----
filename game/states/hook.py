"""渔夫的钩锁。

一个会弹墙的投掷物，加上"钩中人之后沿原路把对方拖回来"那条折线。

和 ball.py 里的 Aura 一样，这个类只是**状态**：怎么飞、拉谁、拉多快，
由 Match 每帧按这里记的东西去算。它自己不持有对 Ball / Match 的引用，
免得又绕成循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pygame.math import Vector2


def polyline_length(path: list[Vector2]) -> float:
    """折线总长。"""
    return sum(
        (path[index + 1] - path[index]).length() for index in range(len(path) - 1)
    )


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
    target: int | None = None       # 钩中的玩家序号；None = 还在飞
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
