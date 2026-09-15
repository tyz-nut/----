"""蜘蛛钉在墙上的那些锚点。

和 laser.py 是一对：都是"撞墙之后留在场上的东西"，区别全在**线的那一头**。

- 激光那条线**两端都钉在墙上**（两个墙点之间连起来），画完就完全定死了，
  跟激光球本人再没有关系。
- 蛛丝只有**一头**钉在墙上，另一头永远连着蜘蛛本人。所以蜘蛛一动，整条丝
  就跟着扫过去——它不是画在地上的一道痕，是绷在蜘蛛和墙之间的一根线。

正因为那一头是活的，这个模块**只存墙上那个点**：蜘蛛那头不用记，球现在在
哪，丝就从哪出发（见 Match.apply_webs）。这也是它和 Beam 最大的不同——Beam
必须自己存两个端点，因为两个端点都不在任何人身上了。

锚点和 Beam 一样把数值**烤在自己身上**（damage_per_second / slow_ratio）：
一根丝从生到死带着的就是它出生那一刻的数值，以后调技能参数不会把场上的旧丝
一起改掉。
"""

from __future__ import annotations

from dataclasses import dataclass

from pygame.math import Vector2

from ..core.segment import distance_to_segment


@dataclass(frozen=True)
class WebAnchor:
    """墙上钉着的一个锚点，蜘蛛和它之间绷着一根丝。"""

    point: Vector2            # 钉在墙上的那一头（另一头是蜘蛛，不记在这里）
    damage_per_second: float  # 压在这根丝上每秒掉多少血
    slow_ratio: float         # 压在这根丝上减速多少（0.5 就是速度砍半）

    def touches(self, origin: Vector2, center: Vector2, radius: float) -> bool:
        """从 origin（蜘蛛现在的位置）拉出来的这根丝，有没有碰到这个球。

        判定是**线段**不是直线：丝只绷在蜘蛛和锚点之间，越过锚点往墙外延长
        出去的部分不算——那截在线实际画出来的范围之外。
        """
        return distance_to_segment(center, origin, self.point) <= radius
