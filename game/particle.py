"""粒子。

Particle 只管"在哪、怎么飘、活多久"，画成什么形状交给子类。目前两种：

- RingParticle  一个越变越大、越变越淡的圆环（撞墙、球撞球）
- TextParticle  往上飘的扣血数字

两者共用一个特点：寿命一到就消失，中间靠 progress（0 → 1）插值。所以基类把
寿命和位移都写好了，子类只需要实现 draw。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame
from pygame.math import Vector2

from .config import DAMAGE_NUMBER_FONT


@dataclass
class Particle:
    """一个粒子。"""

    position: Vector2
    velocity: Vector2 = field(default_factory=Vector2)
    lifetime: float = 1.0
    max_lifetime: float = 1.0
    color: tuple[int, int, int] = (255, 255, 255)
    drag: float = 0.0             # 每秒速度衰减比例，0 就是不减速

    @property
    def progress(self) -> float:
        """活了多久，0（刚出生）→ 1（该消失了）。"""
        if self.max_lifetime <= 0:
            return 1.0
        return 1.0 - self.lifetime / self.max_lifetime

    @property
    def alive(self) -> bool:
        return self.lifetime > 0.0

    def update(self, dt: float) -> None:
        """先按当前速度走，再减速。

        次序不能反：先减速的话第一帧就少走一截，指数衰减的总位移会比
        "初速 / drag" 算出来的理论值少一档（实测少 7%），飘不到预期的高度。
        """
        self.lifetime -= dt
        self.position += self.velocity * dt
        if self.drag > 0.0:
            self.velocity *= max(0.0, 1.0 - self.drag * dt)

    def draw(self, surface: pygame.Surface, offset: Vector2, font) -> None:
        raise NotImplementedError


@dataclass
class RingParticle(Particle):
    """一个从 start_radius 涨到 end_radius 的圆环。"""

    start_radius: float = 6.0
    end_radius: float = 30.0
    width: int = 3

    def draw(self, surface: pygame.Surface, offset: Vector2, font) -> None:
        t = self.progress
        radius = round(self.start_radius + (self.end_radius - self.start_radius) * t)
        if radius <= 0:
            return
        # 用平方淡出：前段还看得清，后段迅速消失，不会留一圈脏影子
        alpha = round(255 * (1.0 - t) ** 2)
        if alpha <= 0:
            return

        center = (round(self.position.x + offset.x), round(self.position.y + offset.y))
        # draw.circle 不吃 alpha，只能先画到一张临时画布上再贴过去
        size = (radius + self.width + 1) * 2
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(
            layer, (*self.color, alpha), (size // 2, size // 2), radius, self.width
        )
        surface.blit(layer, (center[0] - size // 2, center[1] - size // 2))


@dataclass
class TextParticle(Particle):
    """往上飘再淡出的文字（扣血数字）。"""

    text: str = ""

    def draw(self, surface: pygame.Surface, offset: Vector2, font) -> None:
        if font is None or not self.text:
            return
        # 前 70% 完全不透明，最后 30% 才淡出。数字太早开始淡就来不及看清了
        alpha = round(255 * min(1.0, (1.0 - self.progress) / 0.3))
        if alpha <= 0:
            return
        rendered = font.render(self.text, True, self.color)
        rendered.set_alpha(alpha)
        rect = rendered.get_rect(
            center=(round(self.position.x + offset.x), round(self.position.y + offset.y))
        )
        surface.blit(rendered, rect)


class ParticleSystem:
    """一袋粒子：负责推进、回收、绘制。

    用列表 + 每帧过滤，不做对象池——同时存在的粒子也就几十个，
    池化带来的复杂度换不回什么。
    """

    def __init__(self, font: pygame.font.Font | None = None) -> None:
        self.items: list[Particle] = []
        self.font = font

    def add(self, particle: Particle) -> None:
        self.items.append(particle)

    def update(self, dt: float) -> None:
        for particle in self.items:
            particle.update(dt)
        if any(not p.alive for p in self.items):
            self.items = [p for p in self.items if p.alive]

    def draw(self, surface: pygame.Surface, offset: Vector2) -> None:
        for particle in self.items:
            particle.draw(surface, offset, self.font)

    def clear(self) -> None:
        self.items.clear()


def fallback_font() -> pygame.font.Font:
    """没被注入字体时的兜底。扣血数字只有阿拉伯数字，默认字体够用。"""
    return pygame.font.Font(None, DAMAGE_NUMBER_FONT)
