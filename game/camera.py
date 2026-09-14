"""镜头。

目前只干一件事：被打的时候抖一下。

它不是"摄像机"意义上的镜头——没有一个跟着谁走的视点，战场是固定的。
它产出一个**位移偏移量**，绘制战场内容时加到坐标上去，就得到了震动效果。
战场边框、左右栏、底栏都不吃这个偏移，所以看起来是"框里的东西在震"，
而不是整个窗口在晃。
"""

from __future__ import annotations

import math
import random

from pygame.math import Vector2

from .config import SHAKE_DECAY, SHAKE_MAX_OFFSET


class Camera:
    """屏幕抖动。

    用"创伤值"（trauma）模型：每次受击往上加 trauma（0~1，封顶），之后自己线性衰减。
    实际位移取 trauma 的**平方**，而不是它本身——平方让末尾那一段掉得特别快，
    抖动收得干脆；直接线性的话，最后半秒还会一直小幅晃，看着很烦躁。

    每次 update 都随机取方向，所以抖的是"乱"的；想要有方向感的抖动（比如挨打时
    往受力方向顿一下）就得另外记一个方向向量，目前用不上。
    """

    def __init__(self) -> None:
        self.trauma = 0.0
        self.offset = Vector2()

    def shake(self, amount: float) -> None:
        """加一份创伤。同一帧挨了好几下会累加，但封顶在 1.0。"""
        self.trauma = min(1.0, self.trauma + amount)

    def update(self, dt: float) -> None:
        self.trauma = max(0.0, self.trauma - SHAKE_DECAY * dt)
        if self.trauma <= 0.0:
            self.offset.update(0.0, 0.0)
            return
        magnitude = SHAKE_MAX_OFFSET * self.trauma * self.trauma
        angle = random.uniform(0.0, math.tau)
        self.offset.update(math.cos(angle) * magnitude, math.sin(angle) * magnitude)

    def reset(self) -> None:
        """重开一局时用：抖到一半的残留不该带到下一局。"""
        self.trauma = 0.0
        self.offset.update(0.0, 0.0)
