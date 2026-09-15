"""主循环与界面。游戏规则全在 match.py，这里只负责画和收输入。"""

from __future__ import annotations

import os
from enum import Enum, auto
from functools import partial
from pathlib import Path

import pygame
from pygame.math import Vector2

from ..core.arena import Arena
from ..core.ball import Ball
from ..characters import Character, LaserSkill, WebSkill
from ..config.settings import (
    BAR_FILL_MUTE,
    BAR_TEXT,
    BEAM_CORE_WIDTH,
    BEAM_GLOW_WIDTH,
    BEAM_WIDTH,
    BLADE_EDGE_WIDTH,
    BLADE_HUB_RADIUS,
    BLADE_WIDTH,
    COLOR_BG,
    COLOR_BEAM,
    COLOR_BEAM_CORE,
    COLOR_BEAM_GLOW,
    COLOR_BLADE,
    COLOR_BLADE_EDGE,
    COLOR_HOOK,
    COLOR_HOOK_ROPE,
    COLOR_LASER_NODE,
    COLOR_LATCH,
    COLOR_PANEL,
    COLOR_PANEL_BORDER,
    COLOR_PANEL_TITLE,
    COLOR_SKILL_ACTIVE,
    COLOR_SKILL_COOLDOWN,
    COLOR_SKILL_READY,
    COLOR_SKILL_SILENCED,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_THRUST,
    COLOR_WEB,
    COLOR_WEB_ANCHOR,
    COLOR_WINNER,
    DAMAGE_NUMBER_FONT,
    DEBUG_VELOCITY_SCALE,
    FONT_BIG,
    FONT_BODY,
    FONT_CARD_DESC,
    FONT_CARD_NAME,
    FONT_HINT,
    FONT_RIGHT_TITLE,
    FONT_SMALL,
    FONT_TITLE,
    FPS,
    HOOK_RADIUS,
    LASER_NODE_RADIUS,
    MAX_FRAME_TIME,
    PANEL_PADDING,
    PLAYER_NAMES,
    THRUST_TRAIL_LENGTH,
    THRUST_TRAIL_WIDTH,
    WEB_ANCHOR_RADIUS,
    WEB_WIDTH,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)
from ..config.roster import CHARACTERS
from ..fx.effects import Effects
from .layout import build_layout
from ..core.match import Match
from .widgets import Button, draw_bar


class State(Enum):
    """界面对局状态。

    注意 SELECT 有两种样貌：开场时场上空无一物（等玩家选人），以及选完/重开之后
    （角色已就位、静止、等「开始」）。两者规则完全一致，所以不必拆成两个状态。
    """

    SELECT = auto()     # 选择阶段：可改选角色；选齐后能开始
    RUNNING = auto()    # 游戏阶段：小球按动量飞行
    PAUSED = auto()     # 暂停阶段：画面冻结，可继续


STATE_LABEL = {
    State.SELECT: "选择阶段",
    State.RUNNING: "游戏阶段",
    State.PAUSED: "暂停阶段",
}

SHORTCUTS = (
    "空格   开始 / 暂停",
    "R      重开",
    "D      调试",
    "Esc    退出",
)

_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_FONT_FILES = ("msyh.ttc", "simhei.ttf", "simsun.ttc", "NotoSansCJK-Regular.ttc")


def load_font(size: int) -> pygame.font.Font:
    """加载中文字体。

    不走 pygame.font.SysFont / match_font：它们在部分 Windows 环境下枚举系统字体时会
    直接抛异常；按文件路径加载更稳。
    """
    for filename in _FONT_FILES:
        path = _FONT_DIR / filename
        if not path.exists():
            continue
        try:
            return pygame.font.Font(str(path), size)
        except OSError:
            continue
    return pygame.font.Font(None, size)


class Game:
    """一局对决。"""

    def __init__(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption(WINDOW_TITLE)
        self.clock = pygame.time.Clock()
        self.running = False

        self.fonts = {
            size: load_font(size)
            for size in (FONT_SMALL, FONT_BODY, FONT_TITLE, FONT_BIG,
                         FONT_RIGHT_TITLE, FONT_CARD_NAME, FONT_CARD_DESC, FONT_HINT,
                         DAMAGE_NUMBER_FONT)
        }
        self.layout = build_layout(self.screen.get_size(), len(CHARACTERS))
        self.arena = Arena(self.layout.arena)
        # 带字体构造特效。扣血数字用专门的大号字，战场上隔老远也看得清
        self.match = Match(self.arena, Effects(self.fonts[DAMAGE_NUMBER_FONT]))

        self.state = State.SELECT
        self.active_player = 0     # 底栏当前选中的操作对象
        self.debug = False

        self.build_buttons()

    # ---------------- 按钮 ----------------
    def build_buttons(self) -> None:
        action = self.layout.action_buttons
        self.button_start = Button(action[0], "开始", self.start_game)
        self.button_pause = Button(action[1], "暂停", self.toggle_pause)
        self.button_restart = Button(action[2], "重开", self.restart)
        self.button_debug = Button(action[3], "调试", self.toggle_debug)
        self.action_buttons = [
            self.button_start,
            self.button_pause,
            self.button_restart,
            self.button_debug,
        ]

        self.player_buttons = [
            Button(rect, PLAYER_NAMES[index], partial(self.select_player, index))
            for index, rect in enumerate(self.layout.player_buttons)
        ]
        self.character_buttons = [
            Button(rect, character.name, partial(self.pick_character, character),
                   sublabel=character.description)
            for character, rect in zip(CHARACTERS, self.layout.character_cards)
        ]

    def all_buttons(self) -> list[Button]:
        return self.action_buttons + self.player_buttons + self.character_buttons

    def sync_buttons(self) -> None:
        """按当前状态刷新按钮的可用性/文字/高亮。每帧调用。"""
        selecting = self.state is State.SELECT

        self.button_start.enabled = selecting and self.match.both_picked()
        self.button_pause.enabled = self.state is not State.SELECT and not self.match.finished
        self.button_pause.label = "继续" if self.state is State.PAUSED else "暂停"
        self.button_restart.enabled = bool(self.match.balls)   # 场上没角色就无所谓重开
        self.button_debug.enabled = True
        self.button_debug.active = self.debug

        for index, button in enumerate(self.player_buttons):
            button.enabled = selecting
            button.active = selecting and index == self.active_player

        for button in self.character_buttons:
            button.enabled = selecting

    # ---------------- 操作 ----------------
    def start_game(self) -> None:
        if self.state is State.SELECT and self.match.both_picked():
            self.state = State.RUNNING

    def toggle_pause(self) -> None:
        if self.state is State.RUNNING:
            self.state = State.PAUSED
        elif self.state is State.PAUSED:
            self.state = State.RUNNING

    def restart(self) -> None:
        """保留已选角色，重新随机位置与动量，回到选择阶段等「开始」。"""
        if not self.match.balls:
            return
        self.match.restart()
        self.state = State.SELECT

    def toggle_debug(self) -> None:
        self.debug = not self.debug

    def select_player(self, index: int) -> None:
        self.active_player = index

    def pick_character(self, character: Character) -> None:
        """给当前操作对象换上该角色，并在场上随机位置生成（避开对方的球）。"""
        if self.state is not State.SELECT:
            return
        self.match.pick(self.active_player, character)

    # ---------------- 主循环 ----------------
    def run(self) -> None:
        self.running = True
        while self.running:
            # 限幅：只挡畸形帧（拖动窗口、断点、系统休眠后 dt 会突然变成几秒），
            # 正常帧乃至 4fps 的卡顿帧都不会被截断。见 config.MAX_FRAME_TIME 的推导。
            dt = min(self.clock.tick(FPS) / 1000.0, MAX_FRAME_TIME)
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self.handle_key(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_click(event)

    def handle_key(self, key: int) -> None:
        """键盘快捷键，和按钮等价。"""
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif key == pygame.K_SPACE:
            if self.state is State.SELECT:
                self.start_game()
            elif not self.match.finished:
                self.toggle_pause()
        elif key == pygame.K_r:
            self.restart()
        elif key == pygame.K_d:
            self.toggle_debug()

    def handle_click(self, event: pygame.event.Event) -> None:
        for button in self.all_buttons():
            if button.clicked(event):
                button.on_click()
                return

    def update(self, dt: float) -> None:
        if self.state is State.RUNNING:
            self.match.update(dt)

    # ---------------- 绘制 ----------------
    def draw(self) -> None:
        mouse_pos = pygame.mouse.get_pos()
        for button in self.all_buttons():
            button.update_hover(mouse_pos)
        self.sync_buttons()

        self.screen.fill(COLOR_BG)
        self.draw_panels()
        self.arena.draw(self.screen)

        # 镜头抖动只作用于战场内容，不作用于框和左右栏——所以这里夹一次裁剪，
        # 免得抖出去的粒子糊到面板上。物理坐标不受影响，纯视觉。
        offset = self.match.effects.camera.offset
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(self.layout.arena)

        # 光环先画：它是半透明的，盖在球上会把球糊掉
        for ball in self.match.balls.values():
            ball.draw_aura(self.screen, offset)
        # 激光画在球**下面**：它是画在墙上的背景物，压在球上会像割过球面
        for ball in self.match.balls.values():
            self.draw_lasers(ball, offset)
        # 蛛丝也画在球下面：它从蜘蛛身上出发、一路绷到墙上，压在球上会像
        # 一根穿过球体的棍子。画在激光之后，免得被线多的激光盖住
        for ball in self.match.balls.values():
            self.draw_webs(ball, offset)
        for ball in self.match.balls.values():
            self.draw_hook(ball, offset)
        for ball in self.match.balls.values():
            self.draw_thrust_trail(ball, offset)
        self.draw_latch_link(offset)
        for ball in self.match.balls.values():
            ball.draw(self.screen, offset)
        # 刀画在球**上面**：刀根扎在球心附近，压在球下就只剩外面半截，
        # 看着像飘在旁边的另一件东西
        for ball in self.match.balls.values():
            self.draw_blade(ball, offset)
        self.match.effects.draw(self.screen, offset)
        self.draw_latch_label(offset)

        if self.debug:
            for ball in self.match.balls.values():
                ball.draw_debug(
                    self.screen, self.fonts[FONT_SMALL], DEBUG_VELOCITY_SCALE, offset
                )
        self.screen.set_clip(previous_clip)

        self.draw_buttons()

        self.draw_labels()
        self.draw_player_info()
        self.draw_result()
        pygame.display.flip()

    def draw_buttons(self) -> None:
        """画所有按钮。

        角色卡单独一套小字（见 config 的"右栏角色卡"那段）：它要在固定的面板
        高度里塞下 20 张，字号必须比别处小。其余按钮走通用的两档字号。
        """
        body, small = self.fonts[FONT_BODY], self.fonts[FONT_SMALL]
        card_name, card_desc = self.fonts[FONT_CARD_NAME], self.fonts[FONT_CARD_DESC]
        for button in self.action_buttons + self.player_buttons:
            button.draw(self.screen, body, small)
        for button in self.character_buttons:
            button.draw(self.screen, card_name, card_desc)

    def draw_lasers(self, ball: Ball, offset) -> None:
        """画激光：光晕 + 外层 + 芯，三层叠出"发亮"的感觉。

        线不封顶，打久了会很多，所以光晕压得很淡——叠起来才不会糊成一片。
        位点画在两头：攒着待连的那个画大一圈，好让玩家看出来现在是连线模式。
        """
        grid = ball.lasers
        if grid is None:
            return

        def shifted(point) -> tuple[int, int]:
            return round(point.x + offset.x), round(point.y + offset.y)

        for beam in grid.beams:
            start, end = shifted(beam.start), shifted(beam.end)
            pygame.draw.line(self.screen, COLOR_BEAM_GLOW, start, end, BEAM_GLOW_WIDTH)
            pygame.draw.line(self.screen, COLOR_BEAM, start, end, BEAM_WIDTH)
            pygame.draw.line(self.screen, COLOR_BEAM_CORE, start, end, BEAM_CORE_WIDTH)
            for point in (start, end):
                pygame.draw.circle(self.screen, COLOR_LASER_NODE, point,
                                   LASER_NODE_RADIUS)

        if grid.pending is not None:
            # 攒着的那一个：描一圈亮边，和已经连成线的位点区分开
            point = shifted(grid.pending)
            pygame.draw.circle(self.screen, COLOR_LASER_NODE, point,
                               LASER_NODE_RADIUS + 3)
            pygame.draw.circle(self.screen, COLOR_BEAM_CORE, point,
                               LASER_NODE_RADIUS)

    def draw_hook(self, ball: Ball, offset) -> None:
        """画钩锁：从渔夫出发沿折线连到钩尖的一条绳，加钩尖上那个点。

        画在球的**下面**（和吸住那条连线同理）：折线是从渔夫身上出来的，
        压在球上会像一根穿过球的棍子。
        """
        hook = ball.hook
        if hook is None:
            return
        points = [(round(ball.position.x + offset.x), round(ball.position.y + offset.y))]
        points += [
            (round(point.x + offset.x), round(point.y + offset.y)) for point in hook.path
        ]
        if len(points) >= 2:
            pygame.draw.lines(self.screen, COLOR_HOOK_ROPE, False, points, 2)
        pygame.draw.circle(self.screen, COLOR_HOOK, points[-1], HOOK_RADIUS)

    def draw_webs(self, ball: Ball, offset) -> None:
        """画蛛丝：从蜘蛛现在的位置拉一条线到墙上的锚点，锚点画成一个小点。

        只画一层、画得很细：丝不封顶，打久了会有几十根，跟激光那样叠三层
        光晕会糊成一片白雾。它本来也不是发光的东西，是一根绷着的线。

        起点取**当前**位置而不是记住的历史坐标——这正是蛛丝和激光的区别：
        蜘蛛跑到哪，这些线就从哪重新拉出来，看着像一把跟着人扫的扇子。
        """
        if not ball.webs:
            return
        start = ball.center_at(offset)
        for web in ball.webs:
            end = (round(web.point.x + offset.x), round(web.point.y + offset.y))
            pygame.draw.line(self.screen, COLOR_WEB, start, end, WEB_WIDTH)
            pygame.draw.circle(self.screen, COLOR_WEB_ANCHOR, end,
                               WEB_ANCHOR_RADIUS)

    def draw_blade(self, ball: Ball, offset) -> None:
        """画绕身刀：从球心往外伸的一段刃，加根部那个小圆点。

        刃身 + 一条高光，两层就够——刀比激光细得多，再叠光晕会糊成一团，
        看着像刀变粗了而不是变亮了。
        """
        blade = ball.blade
        if blade is None:
            return
        start, end = blade.reach(ball.position)
        start = (round(start.x + offset.x), round(start.y + offset.y))
        end = (round(end.x + offset.x), round(end.y + offset.y))
        pygame.draw.line(self.screen, COLOR_BLADE, start, end, BLADE_WIDTH)
        pygame.draw.line(self.screen, COLOR_BLADE_EDGE, start, end, BLADE_EDGE_WIDTH)
        pygame.draw.circle(self.screen, COLOR_BLADE, start, BLADE_HUB_RADIUS)

    def draw_thrust_trail(self, ball: Ball, offset) -> None:
        """画穿刺的拖尾：从球心**逆着**冲刺方向拖出去的一条尾巴。

        拖尾长度按"还剩多少没冲"缩：刚出手时最长，快冲完就收干净。这样它
        自己就是一根进度条——看尾巴短了就说明这一下快结束了。

        形状用多边形而不是粗线：线是一头粗一头细的锥形，pygame 的 line 画不出
        变宽，得手工给四个角。
        """
        thrust = ball.thrust
        if thrust is None:
            return
        back = -thrust.direction
        length = THRUST_TRAIL_LENGTH * min(1.0, thrust.remaining / THRUST_TRAIL_LENGTH)
        if length <= 1.0:
            return

        center = ball.center_at(offset)
        tip = Vector2(center) + back * length
        # 垂直于冲刺方向的法线，用来把尾巴摊开成一个锥形
        normal = Vector2(-back.y, back.x) * (THRUST_TRAIL_WIDTH / 2)
        head = Vector2(center) + normal
        head_other = Vector2(center) - normal
        pygame.draw.polygon(
            self.screen,
            COLOR_THRUST,
            [
                (round(head.x), round(head.y)),
                (round(head_other.x), round(head_other.y)),
                (round(tip.x), round(tip.y)),
            ],
        )

    def draw_latch_link(self, offset) -> None:
        """吸住的那条连线。画在球**下面**：连的是两个圆心，画在上面就成了
        一根穿过两颗球的棍子。"""
        pair = self.match.latch_pair()
        if pair is None:
            return
        grabber, victim = pair
        pygame.draw.line(self.screen, COLOR_LATCH,
                         grabber.center_at(offset), victim.center_at(offset), 2)

    def draw_latch_label(self, offset) -> None:
        """吸住的倒计时。

        以前吸住是全靠玩家盯血条的——它每秒都在掉血，界面上却一个数字都没有。
        实测一局 81 秒里吸住能占 18 秒，比技能圈的 5 秒长得多，看起来就像
        "读秒结束了还在吸"。这条读秒就是补这个缺口。
        """
        pair = self.match.latch_pair()
        if pair is None:
            return
        grabber, victim = pair
        latch = self.match.latch

        surface = self.fonts[FONT_SMALL].render(
            f"吸住 {latch.remaining:.1f}s", True, COLOR_LATCH
        )
        mid_x = (grabber.position.x + victim.position.x) / 2 + offset.x
        mid_y = (grabber.position.y + victim.position.y) / 2 + offset.y
        rect = surface.get_rect(center=(round(mid_x), round(mid_y - grabber.radius - 26)))
        # 贴着战场边缘时别让字飘到框外去
        rect.clamp_ip(self.layout.arena)
        self.screen.blit(surface, rect)

    def draw_panels(self) -> None:
        for panel in (self.layout.left_panel, self.layout.right_panel, self.layout.bottom_bar):
            pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=10)
            pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=1, border_radius=10)

    def draw_labels(self) -> None:
        title, small = self.fonts[FONT_TITLE], self.fonts[FONT_SMALL]

        # 左栏：当前阶段 + 已选人数
        if self.match.finished:
            status = "对局结束"
        else:
            status = STATE_LABEL[self.state]
            if self.state is State.SELECT and not self.match.both_picked():
                status += f"  {len(self.match.balls)}/{len(PLAYER_NAMES)}"
        self.screen.blit(title.render(status, True, COLOR_TEXT), self.layout.status_pos)

        # 左栏下方：快捷键说明
        x, y = self.layout.shortcut_pos
        for line in SHORTCUTS:
            self.screen.blit(small.render(line, True, COLOR_TEXT_DIM), (x, y))
            y += 24

        # 右栏：标题 + 底部操作提示。这一栏的字比别处小，理由见 config 里
        # "右栏角色卡"那段——面板高度固定，角色会一直加
        hint_font = self.fonts[FONT_HINT]
        self.screen.blit(
            self.fonts[FONT_RIGHT_TITLE].render("角色", True, COLOR_PANEL_TITLE),
            self.layout.panel_title_pos,
        )
        hint = "先选操作对象，再点角色卡"
        self.screen.blit(
            hint_font.render(hint, True, COLOR_TEXT_DIM),
            (self.layout.right_panel.left + PANEL_PADDING,
             self.layout.right_panel.bottom - PANEL_PADDING - hint_font.get_height()),
        )

        # 底栏标签
        self.screen.blit(
            self.fonts[FONT_BODY].render("操作对象", True, COLOR_TEXT),
            self.layout.player_label_pos,
        )

    def draw_player_info(self) -> None:
        """底栏：每个玩家的血条与技能状态。"""
        small = self.fonts[FONT_SMALL]
        for player, ball in sorted(self.match.balls.items()):
            hp_rect = self.layout.hp_bars[player]
            muted = tuple(round(c * BAR_FILL_MUTE) for c in ball.color)
            draw_bar(self.screen, hp_rect, ball.hp / ball.character.max_hp, muted)
            self.blit_centered(f"{ball.hp:.0f}", small, hp_rect)

            skill_rect = self.layout.skill_bars[player]
            text, ratio, color = self.skill_display(ball)
            draw_bar(self.screen, skill_rect, ratio, color)
            self.blit_centered(text, small, skill_rect)

    def skill_display(self, ball: Ball) -> tuple[str, float, tuple[int, int, int]]:
        """技能条的 (文字, 进度 0~1, 填充色)。

        三种形态，颜色和条的走向本身就是信息：

        - 黄条**下降**：技能正在生效，走的是持续时长。这段不计冷却，
          条走完才轮到蓝条
        - 蓝条**增长**：冷却在推进
        - 绿条满格：待发

        被沉默时**不改条的走向，只把它染紫**：沉默封的是"开"这个动作，冷却
        该走还是走，所以条上要表达的仍然是同一件事，只是"现在按了也没用"。
        染紫而不是单开一种状态，是因为沉默没有时长——它不是一段可以画成进度条
        的时间，只是一个开关。冷却走完还封着的话，条就停在满格紫。

        待发时加速球会把当前移速报出来——伤害是速度的平方，攒到多快是个要紧的数，
        只写"待发"就看不出它到底攒了多少。

        **被动技能（激光）走的是一条单独的分支**，因为它既没有冷却也没有生效
        时长，上面那三种形态一个都对不上——硬套的话条会一直停在满格绿写着
        "待发"，等于什么都没说。它的进度该怎么表达，见那条分支自己的说明。
        """
        skill = ball.character.skill

        if isinstance(skill, LaserSkill):
            return self.laser_display(ball, skill)
        if isinstance(skill, WebSkill):
            return self.web_display(ball)

        if ball.skill_active:
            hook = ball.hook
            if hook is not None:
                # 钩锁的生效时长不按秒算，所以黄条画的不是倒计时：
                # 在飞的时候没有进度可言（满格），收线的时候才画收线进度
                if not hook.reeling:
                    return ("抛钩 · 飞行中", 1.0, COLOR_SKILL_ACTIVE)
                return ("抛钩 · 收线", hook.pull_progress, COLOR_SKILL_ACTIVE)
            return (
                f"{skill.name} {ball.skill_active_remaining:.1f}s",
                ball.skill_active_remaining / ball.skill_active_total,
                COLOR_SKILL_ACTIVE,
            )
        if ball.silenced:
            if ball.cooldown_timer > 0:
                return (
                    f"沉默 · {ball.cooldown_timer:.1f}s",
                    1.0 - ball.cooldown_timer / skill.cooldown,
                    COLOR_SKILL_SILENCED,
                )
            # 冷却早走完了，纯粹是被封着
            return "沉默", 1.0, COLOR_SKILL_SILENCED
        if ball.cooldown_timer > 0:
            return (
                f"冷却 {ball.cooldown_timer:.1f}s",
                1.0 - ball.cooldown_timer / skill.cooldown,
                COLOR_SKILL_COOLDOWN,
            )
        # 冷却好了。攒过档的把当前移速报出来——加速是永久叠加的，只报"待发"
        # 玩家就看不出它到底攒到多快了（伤害是速度的平方，这个数很要紧）
        label = "待发" if not ball.boosted else f"{skill.name} |v|{ball.speed:.0f}"
        return label, 1.0, COLOR_SKILL_READY

    def laser_display(self, ball: Ball, skill: LaserSkill
                      ) -> tuple[str, float, tuple[int, int, int]]:
        """激光的技能条。

        它没有冷却，所以条上没法画"还要等多久"。能画的是它**攒到哪一步了**：
        连线模式下条涨到一半（攒了一个点、等下一次撞另一面墙），连成之后重置。
        但这样条会一直在半格和满格之间跳，看不出"已经画了多少根线"。

        所以这里画的是**已经连出来的线数**，文字同时报模式。条本身当成一个
        计数器用：线越多越满。这比"假装有冷却"诚实——玩家真正关心的是场上
        现在有几根线在割人。
        """
        grid = ball.lasers
        beam_count = 0 if grid is None else len(grid.beams)
        armed = grid is not None and grid.armed

        if armed:
            return (f"连线中 · {beam_count} 根", 1.0, COLOR_LASER_NODE)
        if beam_count == 0:
            return ("碰撞布线", 0.0, COLOR_LASER_NODE)
        # 5 根线时条满。再多也不封顶，条就停在满格——这里只是个观感上的刻度，
        # 不影响任何判定
        return (f"激光 {beam_count} 根", min(1.0, beam_count / 5.0), COLOR_BEAM)

    def web_display(self, ball: Ball) -> tuple[str, float, tuple[int, int, int]]:
        """蛛丝的技能条。

        和激光一样是被动，没有冷却也没有生效时长，所以条上画不了"还要等多久"，
        能画的是它**攒到哪一步了**——已经钉出去几根丝。条本身当计数器用。

        刻度取 8 根：蛛丝比激光出得快（撞一下就一根，激光要撞两下），满格自然
        也该来得快一点。这只是观感上的刻度，不影响任何判定。
        """
        anchors = 0 if ball.webs is None else len(ball.webs)
        if anchors == 0:
            return ("结网", 0.0, COLOR_WEB)
        return (f"蛛丝 {anchors} 根", min(1.0, anchors / 8.0), COLOR_WEB)

    def blit_centered(self, text: str, font: pygame.font.Font,
                      rect: pygame.Rect) -> None:
        surface = font.render(text, True, BAR_TEXT)
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def draw_result(self) -> None:
        """对局结束时在战场中央盖一条结果横幅。"""
        if not self.match.finished:
            return
        text = "平局" if self.match.winner is None else f"P{self.match.winner + 1} 获胜"
        surface = self.fonts[FONT_BIG].render(text, True, COLOR_WINNER)
        banner = surface.get_rect(center=self.layout.arena.center)

        backdrop = banner.inflate(64, 32)
        overlay = pygame.Surface(backdrop.size, pygame.SRCALPHA)
        overlay.fill((10, 12, 18, 225))
        self.screen.blit(overlay, backdrop.topleft)
        pygame.draw.rect(self.screen, COLOR_WINNER, backdrop, width=2, border_radius=10)
        self.screen.blit(surface, banner)
