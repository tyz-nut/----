"""极简 UI 控件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame

from .config import (
    COLOR_BAR_BACK,
    COLOR_BAR_BORDER,
    COLOR_BUTTON,
    COLOR_BUTTON_ACTIVE,
    COLOR_BUTTON_BORDER,
    COLOR_BUTTON_DISABLED,
    COLOR_BUTTON_HOVER,
    COLOR_BUTTON_TEXT,
    COLOR_BUTTON_TEXT_DISABLED,
)


@dataclass
class Button:
    """矩形按钮。

    enabled / active / label 由 app 每帧同步（sync_buttons），所以游戏状态一变按钮
    立刻跟着变，按钮自己不需要知道任何游戏规则。
    """

    rect: pygame.Rect
    label: str
    on_click: Callable[[], None]
    enabled: bool = True
    active: bool = False     # 开关类按钮的"已开启/已选中"高亮
    hovered: bool = False
    sublabel: str = ""       # 第二行小字，角色卡用来显示说明

    def update_hover(self, mouse_pos: tuple[int, int]) -> None:
        self.hovered = self.rect.collidepoint(mouse_pos)

    def clicked(self, event: pygame.event.Event) -> bool:
        """这次鼠标事件是否点在了这个可用按钮上。"""
        return (
            self.enabled
            and event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        )

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             small_font: pygame.font.Font | None = None) -> None:
        if not self.enabled:
            fill, text_color = COLOR_BUTTON_DISABLED, COLOR_BUTTON_TEXT_DISABLED
        elif self.active:
            fill, text_color = COLOR_BUTTON_ACTIVE, COLOR_BUTTON_TEXT
        elif self.hovered:
            fill, text_color = COLOR_BUTTON_HOVER, COLOR_BUTTON_TEXT
        else:
            fill, text_color = COLOR_BUTTON, COLOR_BUTTON_TEXT

        pygame.draw.rect(surface, fill, self.rect, border_radius=8)
        pygame.draw.rect(surface, COLOR_BUTTON_BORDER, self.rect, width=1, border_radius=8)

        center = self.rect.center
        if self.sublabel and small_font is not None:
            text = font.render(self.label, True, text_color)
            surface.blit(text, text.get_rect(center=(center[0], center[1] - 12)))
            sub = small_font.render(self.sublabel, True, text_color)
            surface.blit(sub, sub.get_rect(center=(center[0], center[1] + 14)))
        else:
            text = font.render(self.label, True, text_color)
            surface.blit(text, text.get_rect(center=center))


def draw_bar(surface: pygame.Surface, rect: pygame.Rect, ratio: float,
             fill_color: tuple[int, int, int]) -> None:
    """画一条进度条。ratio 会被夹到 0~1。"""
    pygame.draw.rect(surface, COLOR_BAR_BACK, rect, border_radius=4)
    ratio = max(0.0, min(1.0, ratio))
    if ratio > 0:
        filled = rect.copy()
        filled.width = max(1, round(rect.width * ratio))
        pygame.draw.rect(surface, fill_color, filled, border_radius=4)
    pygame.draw.rect(surface, COLOR_BAR_BORDER, rect, width=1, border_radius=4)
