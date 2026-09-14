"""战场：屏幕正中央的一个正方形区域。

战场负责三件事：
1. 把自己画出来；
2. 给出合法的出生点（不越界、且不和已有小球重叠）；
3. 判定并处理小球撞墙。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pygame
from pygame.math import Vector2

from .laser import BOTTOM, LEFT, RIGHT, TOP
from .config import (
    ARENA_BORDER_WIDTH,
    BALL_SPAWN_MARGIN,
    BALL_SPAWN_MAX_TRIES,
    COLOR_ARENA_BORDER,
    COLOR_ARENA_FILL,
)


@dataclass(frozen=True)
class WallHit:
    """一次撞墙：撞在墙面的哪一点、撞的是哪一面。

    以前只返回那个点，因为只有绘制和特效要用它；激光需要知道"是**哪一面**墙"
    （攒着的点换了一面才连线，同一面只是把点挪个位置），所以撞点是哪一个面的
    这件事必须一起报出来——光看坐标反推的话，撞在拐角上就分不清了。
    """

    point: Vector2
    side: str        # laser.LEFT / RIGHT / TOP / BOTTOM


def _fold_axis(value: float, low: float, high: float) -> tuple[float, float]:
    """把一个越界的坐标按镜面反射折回 [low, high]，返回 (新坐标, 撞墙方向)。

    方向是 +1（撞在 low 那面，该往正方向走）、-1（撞在 high 那面）、
    0（没越界）。球和钩锁撞墙都是这个几何，区别只在边界要往内缩一个半径、
    以及球多一个朝向要跟着翻。
    """
    if value < low:
        return low + (low - value), 1.0
    if value > high:
        return high - (value - high), -1.0
    return value, 0.0


class Arena:
    """正方形战场。几何由 layout 算好后传进来，Arena 不关心窗口长什么样。"""

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, COLOR_ARENA_FILL, self.rect)
        pygame.draw.rect(surface, COLOR_ARENA_BORDER, self.rect, width=ARENA_BORDER_WIDTH)

    def bounce_off_walls(self, ball) -> WallHit | None:
        """若小球已经越过墙面，就把它按镜面反射弹回场内。

        这里做的是"镜像反弹"而不是简单的"贴墙 + 反向"：把越界的那一小段位移翻折回场内，
        所以球不会在贴墙的那一帧被吃掉一点距离，长时间弹跳后速度大小保持不变。

        越界深度不会超过半个战场：主循环把单帧时间限制在 MAX_FRAME_TIME 内，
        最多也只会越过 speed * MAX_FRAME_TIME（约 19px）。

        返回撞在墙上的哪一点、哪一面（没撞就是 None）。Arena 只算几何，要不要拿
        这个点画点什么由调用方决定——所以这里不 import 任何绘制相关的东西。
        """
        radius = ball.radius
        left = self.rect.left + radius
        right = self.rect.right - radius
        top = self.rect.top + radius
        bottom = self.rect.bottom - radius

        # 撞点取"球心指向墙面的那个垂足"。两轴同时撞（角落）时后面的会覆盖前面的，
        # 只留一个——反正画出来是个圆，看不出差别
        impact: WallHit | None = None

        x, sign_x = _fold_axis(ball.position.x, left, right)
        y, sign_y = _fold_axis(ball.position.y, top, bottom)
        ball.position.update(x, y)

        # 方向一律走 ball.rebound，不直接改 ball.velocity——球的方向不全在 velocity 上
        # （见 Ball.rebound 的说明），只翻 velocity 会让某些球顶着墙滑出去
        if sign_x:
            ball.rebound("x", sign_x)
            impact = WallHit(
                point=Vector2(
                    self.rect.left if sign_x > 0 else self.rect.right, ball.position.y
                ),
                side=LEFT if sign_x > 0 else RIGHT,
            )
        if sign_y:
            ball.rebound("y", sign_y)
            impact = WallHit(
                point=Vector2(
                    ball.position.x, self.rect.top if sign_y > 0 else self.rect.bottom
                ),
                side=TOP if sign_y > 0 else BOTTOM,
            )

        return impact

    def bounce_point(self, position: Vector2, velocity: Vector2) -> bool:
        """把一个**没有体积**的点（钩尖）按镜面反射折回场内，返回是否撞到了墙。

        和 bounce_off_walls 是同一套几何，区别只有两点：半径取 0（点是无限小的），
        以及点没有朝向，所以翻速度就够了，不用像球那样兼顾 heading。
        """
        x, sign_x = _fold_axis(position.x, self.rect.left, self.rect.right)
        y, sign_y = _fold_axis(position.y, self.rect.top, self.rect.bottom)
        position.update(x, y)
        if sign_x:
            velocity.x = sign_x * abs(velocity.x)
        if sign_y:
            velocity.y = sign_y * abs(velocity.y)
        return bool(sign_x or sign_y)

    def bounce_rigid_pair(self, first, second, velocity: Vector2
                          ) -> tuple[Vector2, Vector2 | None]:
        """把粘在一起的两个球当成一个刚体来撞墙。

        为什么不能各自调用 bounce_off_walls：那样两个球会被墙分别弹开，
        等于从中间把这一对撕成两半。这里取两球合起来的包围盒跟墙比，
        谁越界就整体平移回去、整体翻速度。

        比"用一个包住两球的大圆"更准：包围盒正好贴住墙时才是真相切的时刻。

        返回 (修正后的速度, 撞点或 None)。撞点只有一个，取这对球的包围盒中点上
        ——反正画出来是个圆，够用了。
        """
        rect = self.rect
        left = min(first.position.x - first.radius, second.position.x - second.radius)
        right = max(first.position.x + first.radius, second.position.x + second.radius)
        top = min(first.position.y - first.radius, second.position.y - second.radius)
        bottom = max(first.position.y + first.radius, second.position.y + second.radius)

        velocity = Vector2(velocity)
        shift_x = shift_y = 0.0
        if left < rect.left:
            shift_x = rect.left - left
            velocity.x = abs(velocity.x)
        elif right > rect.right:
            shift_x = rect.right - right
            velocity.x = -abs(velocity.x)
        if top < rect.top:
            shift_y = rect.top - top
            velocity.y = abs(velocity.y)
        elif bottom > rect.bottom:
            shift_y = rect.bottom - bottom
            velocity.y = -abs(velocity.y)

        if not (shift_x or shift_y):
            return velocity, None

        shift = Vector2(shift_x, shift_y)
        first.position += shift
        second.position += shift
        # 撞点在移动**之后**算：这时包围盒刚好贴着墙，取的是贴墙那条边的中点
        return velocity, self._pair_impact(first, second, shift_x, shift_y)

    def _pair_impact(self, first, second, shift_x: float, shift_y: float) -> Vector2:
        """这一对刚体撞在墙上的那个点。

        水平方向优先：两轴同时撞（角落）时只报一个点就够了，画出来是个圆，
        多报一个反而重叠。
        """
        mid_x = (first.position.x + second.position.x) / 2
        mid_y = (first.position.y + second.position.y) / 2
        if shift_x:
            return Vector2(self.rect.left if shift_x > 0 else self.rect.right, mid_y)
        return Vector2(mid_x, self.rect.top if shift_y > 0 else self.rect.bottom)

    def clamp_inside(self, position: Vector2, radius: int) -> None:
        """把圆心硬夹回"球能待的地方"：距离墙面至少一个半径。

        和 bounce_off_walls 的区别是**不碰速度、也不镜像**——它是给那些不按自己
        动量走的球兜底的（渔夫定身时、被钩回来时）：它们不 bounce，但一样会被
        球球分离推一把、被折线拖着贴着墙走，光靠"跳过撞墙判定"会让它们留在墙外。

        夹而不是折，是因为这些球的位置是**被摆**的，不是飞过去的：折一下会凭空
        给出一段镜像位移，夹回去只是把越界的那一点抹掉。而且夹是连续的——被拖
        着走过墙角时球会贴着墙滑，不会突然跳一下。
        """
        position.update(
            min(max(position.x, self.rect.left + radius), self.rect.right - radius),
            min(max(position.y, self.rect.top + radius), self.rect.bottom - radius),
        )

    def wall_crossing(self, start: Vector2, end: Vector2) -> Vector2:
        """线段 start→end 与墙面的交点（start 在场内，end 已经越界）。

        给钩锁记折线拐角用的。不能直接拿越界后的坐标当拐角——那一点在墙**外面**
        （最多出去 speed×dt，900px/s 下就是 15 像素），收线时敌人会跟着在墙外走
        一截，看着像穿墙。这里精确算出穿墙的那一点，拐角就正好压在墙上。

        两轴同时穿（角落）时取先穿的那个，也就是把拐角算在它真正先碰到的那面墙上。
        """
        crossings = []
        if end.x < self.rect.left:
            crossings.append((self.rect.left - start.x) / (end.x - start.x))
        elif end.x > self.rect.right:
            crossings.append((self.rect.right - start.x) / (end.x - start.x))
        if end.y < self.rect.top:
            crossings.append((self.rect.top - start.y) / (end.y - start.y))
        elif end.y > self.rect.bottom:
            crossings.append((self.rect.bottom - start.y) / (end.y - start.y))
        if not crossings:
            return Vector2(end)
        # start 在场内、end 越界，说明这个轴上两者必然不等，分母不会为 0
        return start + (end - start) * min(crossings)

    def random_spawn_point(
        self,
        radius: int,
        others: list,
        gap: float = 0.0,
    ) -> Vector2:
        """随机取一个出生点：完全落在战场内，且与 others 中的每个球至少间隔 gap。

        采用拒绝采样：随机撒点直到满足条件；尝试次数用尽时返回最后一次结果兜底
        （战场空间远大于球体时不会触发）。
        """
        left = self.rect.left + radius + BALL_SPAWN_MARGIN
        right = self.rect.right - radius - BALL_SPAWN_MARGIN
        top = self.rect.top + radius + BALL_SPAWN_MARGIN
        bottom = self.rect.bottom - radius - BALL_SPAWN_MARGIN

        candidate = Vector2((left + right) / 2, (top + bottom) / 2)
        for _ in range(BALL_SPAWN_MAX_TRIES):
            candidate = Vector2(random.uniform(left, right), random.uniform(top, bottom))
            if all(
                candidate.distance_to(other.position) >= radius + other.radius + gap
                for other in others
            ):
                break
        return candidate
