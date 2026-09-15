"""界面几何。

所有矩形都在这里算好，app 只管拿去用，不自己算坐标。想调版面只改这个文件和 config。
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from ..config.settings import (
    ACTION_BUTTON_GAP,
    ACTION_BUTTON_HEIGHT,
    ARENA_SIZE,
    BAR_HEIGHT,
    BOTTOM_BAR_HEIGHT,
    CARD_COLUMNS,
    CARD_COLUMN_GAP,
    CARD_GAP,
    CARD_HEIGHT,
    GROUP_GAP,
    HP_BAR_WIDTH,
    INFO_GAP,
    LEFT_PANEL_WIDTH,
    PADDING,
    PANEL_PADDING,
    PANEL_TITLE_HEIGHT,
    PLAYER_BUTTON_HEIGHT,
    PLAYER_BUTTON_WIDTH,
    PLAYER_LABEL_WIDTH,
    RIGHT_PANEL_WIDTH,
    SKILL_BAR_WIDTH,
    STATUS_HEIGHT,
)


@dataclass(frozen=True)
class Layout:
    """一份算好的版面。"""

    window: pygame.Rect
    left_panel: pygame.Rect
    right_panel: pygame.Rect
    bottom_bar: pygame.Rect
    arena: pygame.Rect
    action_buttons: list[pygame.Rect]
    player_buttons: list[pygame.Rect]
    character_cards: list[pygame.Rect]
    hp_bars: list[pygame.Rect]
    skill_bars: list[pygame.Rect]
    status_pos: tuple[int, int]
    panel_title_pos: tuple[int, int]
    player_label_pos: tuple[int, int]
    shortcut_pos: tuple[int, int]


def build_layout(window_size: tuple[int, int], character_count: int) -> Layout:
    window = pygame.Rect(0, 0, *window_size)
    width, height = window_size

    bottom_bar = pygame.Rect(
        PADDING,
        height - PADDING - BOTTOM_BAR_HEIGHT,
        width - 2 * PADDING,
        BOTTOM_BAR_HEIGHT,
    )
    panel_height = bottom_bar.top - 2 * PADDING
    left_panel = pygame.Rect(PADDING, PADDING, LEFT_PANEL_WIDTH, panel_height)
    right_panel = pygame.Rect(
        width - PADDING - RIGHT_PANEL_WIDTH, PADDING, RIGHT_PANEL_WIDTH, panel_height
    )

    # 战场在"左右两栏之间、底栏之上"的剩余区域里居中。
    # 因为左右栏不等宽、下方还有底栏，战场自然就偏离了窗口正中——这就是"偏置"。
    play_region = pygame.Rect(
        left_panel.right + PADDING,
        PADDING,
        right_panel.left - left_panel.right - 2 * PADDING,
        panel_height,
    )
    arena = pygame.Rect(0, 0, ARENA_SIZE, ARENA_SIZE)
    arena.center = play_region.center

    # --- 左栏：状态文字 + 四个操作按钮，自上而下排 ---
    inner_left = left_panel.left + PANEL_PADDING
    inner_width = left_panel.width - 2 * PANEL_PADDING
    status_pos = (inner_left, left_panel.top + PANEL_PADDING)
    buttons_top = left_panel.top + STATUS_HEIGHT
    action_buttons = []
    for index in range(4):
        y = buttons_top + index * (ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP)
        action_buttons.append(pygame.Rect(inner_left, y, inner_width, ACTION_BUTTON_HEIGHT))

    # --- 右栏：标题 + 角色卡（按 CARD_COLUMNS 列排成网格）---
    panel_title_pos = (right_panel.left + PANEL_PADDING, right_panel.top + PANEL_PADDING)
    cards_top = right_panel.top + PANEL_TITLE_HEIGHT
    cards_left = right_panel.left + PANEL_PADDING
    cards_width = right_panel.width - 2 * PANEL_PADDING
    # 列宽由面板宽度均分，不是写死的：左中右三栏的宽度都在 config 里，
    # 卡片跟着面板走，改面板宽度不用回来改这里
    card_width = (cards_width - (CARD_COLUMNS - 1) * CARD_COLUMN_GAP) // CARD_COLUMNS
    column_pitch = card_width + CARD_COLUMN_GAP
    row_pitch = CARD_HEIGHT + CARD_GAP
    character_cards = []
    for index in range(character_count):
        row, column = divmod(index, CARD_COLUMNS)
        character_cards.append(pygame.Rect(
            cards_left + column * column_pitch,
            cards_top + row * row_pitch,
            card_width,
            CARD_HEIGHT,
        ))

    # --- 底栏：每个玩家一组 [名字按钮] 血条 技能条 ---
    button_y = bottom_bar.centery - PLAYER_BUTTON_HEIGHT // 2
    bar_y = bottom_bar.centery - BAR_HEIGHT // 2
    player_label_pos = (bottom_bar.left + PANEL_PADDING, bottom_bar.centery - 12)
    player_buttons: list[pygame.Rect] = []
    hp_bars: list[pygame.Rect] = []
    skill_bars: list[pygame.Rect] = []

    x = bottom_bar.left + PLAYER_LABEL_WIDTH
    for _ in range(2):
        player_buttons.append(pygame.Rect(x, button_y, PLAYER_BUTTON_WIDTH, PLAYER_BUTTON_HEIGHT))
        x += PLAYER_BUTTON_WIDTH + INFO_GAP
        hp_bars.append(pygame.Rect(x, bar_y, HP_BAR_WIDTH, BAR_HEIGHT))
        x += HP_BAR_WIDTH + INFO_GAP
        skill_bars.append(pygame.Rect(x, bar_y, SKILL_BAR_WIDTH, BAR_HEIGHT))
        x += SKILL_BAR_WIDTH + GROUP_GAP

    # 快捷键说明放到左栏下方的大片空位里
    shortcut_pos = (left_panel.left + PANEL_PADDING, left_panel.bottom - 132)

    return Layout(
        window=window,
        left_panel=left_panel,
        right_panel=right_panel,
        bottom_bar=bottom_bar,
        arena=arena,
        action_buttons=action_buttons,
        player_buttons=player_buttons,
        character_cards=character_cards,
        hp_bars=hp_bars,
        skill_bars=skill_bars,
        status_pos=status_pos,
        panel_title_pos=panel_title_pos,
        player_label_pos=player_label_pos,
        shortcut_pos=shortcut_pos,
    )
