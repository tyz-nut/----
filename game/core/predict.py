"""预判：这颗球接下来会不会撞上什么。

给幻影刺客的"即将被撞到"用。做法是把场上的东西**沿各自当前的速度外推**一小
段时间，隔几步采一个样，看两个形状会不会碰上。

## 它是有意的近似

只外推，不模拟：撞墙、被别人推、技能中途结束、钩锁半路弹墙，这些一概不管。
理由是它只需要在"真的要撞上了"这件事上足够准——那件事发生在很短的未来里，
外推几步就看出来了；而那些中途变数离得更远，本来也不该触发。所以
react_seconds 别填太大，填大了会开始频繁误报。

球和球之间用**相对**运动（两边各自外推再相减），所以迎面对冲也能提前看出来，
不用把速度换算成相对速度再解方程。

各家的形状怎么外推，写在下面各自的函数里。共同点是这里**只读**它们的几何
参数，不改任何东西。

## 什么算"会撞上"

对方的球，以及对方留在场上的东西：绕身刀、巨锤、激光、蛛丝、飞在半路的
钩锁、水里游着的鱼。这正是"敌人的攻击手段"的全集——每一个都会让刺客掉血
或被抓。

不包括蝙蝠圈那种**范围场**：它是"站在里面就慢慢掉血"，不是"撞上"。刺客
躲的是撞击，不是消耗。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pygame.math import Vector2

from .segment import distance_to_segment

if TYPE_CHECKING:
    from .ball import Ball
    from .match import Match


def will_be_hit(match: Match, ball: Ball, horizon: float,
                samples: int = 8) -> bool:
    """把 ball 沿当前动量外推 horizon 秒，看这一路上会不会撞上什么。

    samples 是采样步数：外推是一条直线，但对方在转的东西（刀、锤）不是，
    所以中间要采几脚。8 步在 0.3 秒的量级上足够——再密也只是把同一件事多
    确认几遍。

    自己已经死了、场上没有别人，都直接回答 False。
    """
    if horizon <= 0.0 or samples < 1 or not ball.alive:
        return False

    mine_velocity = ball.effective_velocity
    # 只问"对方"：自己的刀和锤不会砸到自己，自己的钩锁也不钩自己
    others = [
        (other, other.effective_velocity)
        for other in match.combatants()
        if other is not ball and other.alive
    ]
    if not others:
        return False

    for step in range(1, samples + 1):
        t = horizon * step / samples
        mine = ball.position + mine_velocity * t
        for other, velocity in others:
            center = other.position + velocity * t
            if mine.distance_to(center) <= ball.radius + other.radius:
                return True
            if _spun_hits(ball, mine, other, center, t):
                return True
            if _web_hits(ball, mine, other, center):
                return True
            if _hook_hits(ball, mine, other, t):
                return True
            if _fish_hits(match, ball, mine, other, t):
                return True
            if _laser_hits(ball, mine, other):
                return True
    return False


def _spun(angle: float, angular_speed: float, t: float) -> Vector2:
    """一个绕着自己转的东西，t 秒之后指向哪个方向。"""
    spun = angle + angular_speed * t
    return Vector2(math.cos(spun), math.sin(spun))


def _spun_hits(ball: Ball, mine: Vector2, other: Ball, center: Vector2,
               t: float) -> bool:
    """对方身上转着的东西：绕身刀和绕身锤。

    这两样是"挂在对方身上、跟着它平移、同时自己转"的东西，所以外推要分两步：
    中心跟着对方走（center 已经算好），角度加上 ω·t。刀是一截线段、锤是一个
    点（锤头），判定各自和实际结算时保持一致（见 Match.apply_blades /
    apply_hammer）。
    """
    blade = other.blade
    if blade is not None:
        direction = _spun(blade.angle, blade.angular_speed, t)
        start = center + direction * blade.inner_radius
        end = center + direction * blade.outer_radius
        if distance_to_segment(mine, start, end) <= ball.radius:
            return True

    hammer = other.hammer
    if hammer is not None:
        head = center + _spun(hammer.angle, hammer.angular_speed, t) * hammer.outer_radius
        if mine.distance_to(head) <= ball.radius + hammer.head_radius:
            return True
    return False


def _web_hits(ball: Ball, mine: Vector2, other: Ball, center: Vector2) -> bool:
    """对方的蛛丝。

    丝的两头一头钉在墙上（不动）、一头是蜘蛛本人（跟着它动），所以这里用
    **对方外推之后的位置**当那一头——丝是会跟着人扫过来的，这一点不体现出来
    就完全预判不到它。
    """
    if not other.webs:
        return False
    return any(web.touches(center, mine, ball.radius) for web in other.webs)


def _hook_hits(ball: Ball, mine: Vector2, other: Ball, t: float) -> bool:
    """对方甩出来的钩锁。

    只看钩尖，和实际命中判定一致（Match.fly_hook 量的是钩尖到对方圆心的距离）。
    收线中的不算：那时候钩已经咬住人了，钩尖贴着被钩的那位，不再是一个会
    "扫过来"的东西。

    钩锁是**会弹墙**的（而且鱼线有 900 像素那么长，能飞两秒多），外推的直线
    迟早会偏离它真实的折线路径。所以这条只在很短的 horizon 里可信，也正是这个
    技能需要的量级。
    """
    hook = other.hook
    if hook is None or hook.reeling:
        return False
    tip = hook.position + hook.velocity * t
    return mine.distance_to(tip) <= ball.radius


def _fish_hits(match: Match, ball: Ball, mine: Vector2, other: Ball,
               t: float) -> bool:
    """对方放出来的鱼（渔夫钩空之后那些）。

    **不能像钩锁那样拿当前速度外推**：钩锁在两堵墙之间走的是直线，鱼从出水那
    一刻起就一直在拐弯（见 states/fish.py 的 steer）。而在拐弯最厉害的那几帧，
    它速度指的方向和它真正要去的地方差得远——偏偏那几帧就是它快咬到人的时候，
    照速度外推会正好在那里漏掉。

    所以这里按"鱼接下来是**直线扑向它此刻正在追的那个人**"来外推。追踪的路径
    本来就是朝目标收紧的，取"朝着目标"这一阶，比取当前切线准得多：只要你就是
    它锁的那个人，这条就会亮。

    代价是它从"正在拐过来"这一刻起就报"要挨咬了"——比真咬到早一点。对这个
    技能来说恰好是对的：刺客要的就是**早**，晚了就没有闪的余地了。

    距离取半径和（鱼半径 + 自己半径），和真的咬人时那条判定一致
    （Match.update_fishes 量的是鱼心到敌人圆面）。
    """
    if not other.fishes:
        return False
    for fish in other.fishes:
        # 鱼追的是"放它的人眼里的敌人"，所以得拿 owner 去问，不能拿刺客自己问
        prey = match.nearest_enemy(other, fish.position)
        if prey is None:
            continue
        offset = prey.position - fish.position
        if offset.length_squared() <= 1e-12:
            return True
        ahead = fish.position + offset.normalize() * (fish.speed * t)
        if mine.distance_to(ahead) <= ball.radius + fish.radius:
            return True
    return False


def _laser_hits(ball: Ball, mine: Vector2, other: Ball) -> bool:
    """对方的激光。线画完就钉死在墙上，所以不用管 t，每步采样的结果都一样。"""
    grid = other.lasers
    if grid is None:
        return False
    return any(beam.hits(mine, ball.radius) for beam in grid.beams)
