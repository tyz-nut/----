"""极简 UI 控件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame

from ..config.settings import (
    COLOR_BAR_BACK,
    COLOR_BAR_BORDER,
    COLOR_BUTTON,
    COLOR_BUTTON_ACTIVE,
    COLOR_BUTTON_BORDER,
    COLOR_BUTTON_DISABLED,
    COLOR_BUTTON_HOVER,
    COLOR_BUTTON_TEXT,
    COLOR_BUTTON_TEXT_DISABLED,
    COLOR_SLIDER_FILL,
    COLOR_SLIDER_KNOB,
    COLOR_SLIDER_KNOB_HOVER,
    COLOR_SLIDER_TRACK,
    SLIDER_KNOB_RADIUS,
    SLIDER_STEPS,
    SLIDER_TRACK_HEIGHT,
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
            # 两行字的间距按**按钮高度**算，不写死：角色卡的高度是会调的
            # （见 config 的 CARD_HEIGHT），写死的话卡片一压缩两行字就叠在一起了
            offset = round(self.rect.height * 0.20)
            text = font.render(self.label, True, text_color)
            surface.blit(text, text.get_rect(center=(center[0], center[1] - offset)))
            sub = small_font.render(self.sublabel, True, text_color)
            surface.blit(sub, sub.get_rect(center=(center[0], center[1] + offset)))
        else:
            text = font.render(self.label, True, text_color)
            surface.blit(text, text.get_rect(center=center))


@dataclass
class Slider:
    """一条横滑块，把 [minimum, maximum] 里的数拧来拧去。

    只管"拧"这件事：值变了要拿它干什么由 app 决定（这里是拿去设
    Match.time_scale.base）。和 Button 一样，它不认识任何游戏规则。

    拖动**吸附到 SLIDER_STEPS 档**：连续取值会让值显示成 1.37x 这种没意义的
    数，而且同一个位置很难拧回去。吸附之后每一档都是干净的。

    按下就跳：鼠标按在滑轨上任意一点，圆头直接跟过去。要"必须抓住圆头才能拖"
    的话，窄条上很难按中，纯属跟自己较劲。
    """

    rect: pygame.Rect          # 整条控件占的横条：数值、滑轨、标签三行都在里面
    minimum: float
    maximum: float
    value: float
    label: str = ""
    dragging: bool = False
    hovered: bool = False

    @property
    def ratio(self) -> float:
        span = self.maximum - self.minimum
        if span <= 0.0:
            return 0.0
        return max(0.0, min(1.0, (self.value - self.minimum) / span))

    @property
    def track(self) -> pygame.Rect:
        """滑轨本身：比 rect 细，落在 rect 竖直方向的中线上。

        三行（数值 / 滑轨 / 标签）按 rect 高度均分，不写死像素——左栏的高度
        是会跟着窗口变的，写死的话窗口一矮标签就叠到别的东西上了。
        """
        height = min(SLIDER_TRACK_HEIGHT, self.rect.height)
        return pygame.Rect(
            self.rect.left,
            self.rect.centery - height // 2,
            self.rect.width,
            height,
        )

    def _row_center(self, index: int) -> int:
        """三行里第 index 行的中心 y。0 = 数值，1 = 滑轨，2 = 标签。"""
        row = self.rect.height / 3.0
        return round(self.rect.top + row * (index + 0.5))

    @property
    def knob_center(self) -> tuple[int, int]:
        track = self.track
        # 圆头半径要从可拧范围里让出来，否则拧到两头时圆头会探出滑轨，
        # 看着像能再往外拧一点
        left = track.left + SLIDER_KNOB_RADIUS
        right = track.right - SLIDER_KNOB_RADIUS
        return (round(left + (right - left) * self.ratio), track.centery)

    def set_ratio(self, ratio: float) -> None:
        """按比例定位，吸附到整数档。"""
        ratio = max(0.0, min(1.0, ratio))
        ratio = round(ratio * SLIDER_STEPS) / SLIDER_STEPS
        self.value = self.minimum + ratio * (self.maximum - self.minimum)

    def _ratio_at(self, x: int) -> float:
        track = self.track
        left = track.left + SLIDER_KNOB_RADIUS
        right = track.right - SLIDER_KNOB_RADIUS
        if right <= left:
            return 0.0
        return (x - left) / (right - left)

    def update_hover(self, mouse_pos: tuple[int, int]) -> None:
        self.hovered = self.rect.collidepoint(mouse_pos)

    def handle(self, event: pygame.event.Event) -> bool:
        """处理鼠标事件，返回"这次事件被我吃了"。

        app 拿着这个返回值决定还要不要往下传：拖着滑块经过别的按钮时，不能
        顺手把那些按钮也点亮了。
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.dragging = True
                self.set_ratio(self._ratio_at(event.pos[0]))
                return True
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = self.dragging
            self.dragging = False
            return was
        if event.type == pygame.MOUSEMOTION and self.dragging:
            self.set_ratio(self._ratio_at(event.pos[0]))
            return True
        return False

    def draw(self, surface: pygame.Surface, small_font: pygame.font.Font) -> None:
        track = self.track
        pygame.draw.rect(surface, COLOR_SLIDER_TRACK, track, border_radius=3)

        # 已经拧过去的那一段。用圆头位置当分界，和圆头严格对齐
        knob_x = self.knob_center[0]
        filled = pygame.Rect(track.left, track.top, max(0, knob_x - track.left), track.height)
        if filled.width > 0:
            pygame.draw.rect(surface, COLOR_SLIDER_FILL, filled, border_radius=3)

        knob_color = COLOR_SLIDER_KNOB_HOVER if (self.hovered or self.dragging) else COLOR_SLIDER_KNOB
        pygame.draw.circle(surface, knob_color, self.knob_center, SLIDER_KNOB_RADIUS)

        # 数值写在滑轨上方、标签在下方，都居中——拧的时候视线在圆头上，
        # 数值离它越近越好读
        text = small_font.render(f"{self.value:.2f}x", True, COLOR_BUTTON_TEXT)
        surface.blit(text, text.get_rect(center=(self.rect.centerx, self._row_center(0))))
        if self.label:
            label = small_font.render(self.label, True, COLOR_BUTTON_TEXT)
            surface.blit(label, label.get_rect(center=(self.rect.centerx, self._row_center(2))))


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
