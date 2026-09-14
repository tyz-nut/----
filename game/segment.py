"""线段几何。

只有一个函数，但它被两处共用——激光画在墙上的线、武士绕着自己转的刀，
两样都是"一段线段，球面挨上就算碰到"。放在这里而不是塞进其中一边，
免得另一边 import 一个名字叫 laser 的模块只为拿一个算距离的函数。
"""

from __future__ import annotations

from pygame.math import Vector2


def distance_to_segment(point: Vector2, start: Vector2, end: Vector2) -> float:
    """点到线段的最短距离。

    注意是**线段**不是直线：投影落在两端之外时取端点到点的距离，
    否则贴着线段延长线站的球会被误判成"碰到了"。

    线段退化成一点（start == end）时按点到点处理——除零会算出 nan，
    而 nan 参与的比较一律为假，"刚好不挨着"就会变成"永远不挨着"。
    """
    segment = end - start
    length_squared = segment.length_squared()
    if length_squared <= 1e-12:
        return (point - start).length()
    t = max(0.0, min(1.0, (point - start).dot(segment) / length_squared))
    return (point - (start + segment * t)).length()
