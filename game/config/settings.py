"""全局配置：所有可调参数集中在这里，方便统一调参。"""

# ---------------- 窗口 ----------------
WINDOW_TITLE = "小球对决"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
FPS = 60

# 单帧最多推进的时间（秒）。用途：卡顿（拖窗口、断点、系统休眠）后 dt 会突然变成几秒，
# 一帧的巨大位移会把小球甩出战场且再也回不来，这里把这类畸形帧截断。
#
# 危险线：单步位移 > 战场可活动宽度(600 - 2*半径 = 556px) 时，镜像反弹只折返一次会失效
#         → 380px/s 下即 dt > 1.463s。实测 dt ≤ 1.4s 时位置/速度与细分步进完全一致（误差 0）。
# 0.25s × 380px/s = 95px，留 5.9 倍余量；且只对 4fps 以下的帧生效，不影响正常游玩。
#
# 注意：调大 BALL_SPEED_MAX 时要回头验算这个余量。加速技能现在是**永久叠加**的
# （见 config/roster.py 的 spawn_speed_gain），移速会随时间越涨越高，
# 所以这里的安全边界不再是 BALL_SPEED_MAX，而是它乘上最终的加速倍率。
# 好消息是撞速是平方伤害，速度一高当场就见胜负，一局叠不了几档；
# 真正要防的只是"某局莫名其妙打了很久"，那时上面那条 556px 的线才会被踩到。
MAX_FRAME_TIME = 0.25

# ---------------- 布局 ----------------
PADDING = 24                 # 各区块之间的留白
PANEL_PADDING = 14           # 面板内部内容距面板边框的留白
LEFT_PANEL_WIDTH = 200       # 左栏：操作按钮
RIGHT_PANEL_WIDTH = 300      # 右栏：角色选择。两列卡片要放得下，
                             # 比单列时宽了 40（战场仍有余量，见下）
BOTTOM_BAR_HEIGHT = 96       # 底栏：P1/P2 操作对象
ARENA_SIZE = 600             # 正方形战场边长
ARENA_BORDER_WIDTH = 2       # 战场边框粗细

STATUS_HEIGHT = 60           # 左栏顶部状态文字占位
ACTION_BUTTON_HEIGHT = 52
ACTION_BUTTON_GAP = 14

# ---------------- 左栏游戏速度滑块 ----------------
# 滑块拧的是 TimeScale.base，技能压的减速**乘**在它上面（见 core/timescale.py）。
# 所以 0.25 再碰上技能 0.25 就是 0.0625x——极值不用管，这是定下来的叠加方式
TIME_SCALE_MIN = 0.25
TIME_SCALE_MAX = 3.0
TIME_SCALE_DEFAULT = 1.0

SPEED_SLIDER_HEIGHT = 48     # 整条滑块占多高。里面均分成三行：数值 / 滑轨 / 标签
SPEED_SLIDER_GAP = 18        # 滑块离上方按钮的间距
SPEED_LABEL_GAP = 14         # 滑块离下方快捷键说明的间距
SLIDER_TRACK_HEIGHT = 6      # 滑轨粗细
SLIDER_KNOB_RADIUS = 8       # 滑块圆头半径
SLIDER_STEPS = 20            # 拖动时的吸附档数。拧到 2.37x 没什么意义

COLOR_SLIDER_TRACK = (40, 46, 60)
COLOR_SLIDER_FILL = (72, 132, 196)     # 滑块左侧已经拧过去的那一段
COLOR_SLIDER_KNOB = (214, 222, 238)
COLOR_SLIDER_KNOB_HOVER = (255, 255, 255)

# ---------------- 右栏角色卡 ----------------
# 排成 CARD_COLUMNS 列的网格。这几个数是照着"最多放得下多少张"反推的：
# 面板可用高度 ≈ 632 - 标题 40 - 底部提示 28 = 564，一行占 CARD_HEIGHT + CARD_GAP
# = 56，正好 10 行；两列就是 20 张。加角色超过 20 个要回头调这几个数。
#
# 卡片做小是因为角色会一直加，而面板高度是固定的——与其等放不下了再临时压缩，
# 不如一次压到位。改小之后字也得更着改，见 FONT_CARD_NAME / FONT_CARD_DESC。
CARD_COLUMNS = 2             # 卡片排几列
CARD_HEIGHT = 48             # 单张卡的高度（里面要塞两行字，见 ui.Button.draw）
CARD_GAP = 8                 # 行间距
CARD_COLUMN_GAP = 8          # 列间距

PANEL_TITLE_HEIGHT = 40      # 右栏标题占位。标题字号跟着降到 FONT_RIGHT_TITLE

PLAYER_LABEL_WIDTH = 140     # 底栏"操作对象"文字占位
PLAYER_BUTTON_WIDTH = 96
PLAYER_BUTTON_HEIGHT = 48

# 底栏每个玩家一组：[名字按钮] 血条 技能条
HP_BAR_WIDTH = 200
SKILL_BAR_WIDTH = 132
BAR_HEIGHT = 22
INFO_GAP = 12                # 组内元素间距
GROUP_GAP = 56               # 两组之间的间距

# ---------------- 小球 ----------------
BALL_SPAWN_MARGIN = 8        # 出生点球面距墙的最小距离
BALL_SPAWN_MIN_GAP = 30      # 两球之间的最小空隙（球面到球面的距离）
BALL_SPAWN_MAX_TRIES = 200   # 随机撒点的最大尝试次数
BALL_SPEED_MIN = 220.0       # 初始动量大小下限（像素/秒）
BALL_SPEED_MAX = 380.0       # 初始动量大小上限（像素/秒）

SEPARATION_EPSILON = 0.01    # 碰撞分离时额外推开的距离。刚好相切时浮点误差可能让
                             # 心距算出 43.99999999999999，下一帧又被判定成"还在重叠"，
                             # 接触标记就永远复位不了，之后整套伤害都会失效。
LATCH_RELEASE_SPEED = 260.0  # 吸住结束时两球弹开的速度（像素/秒）
HOOK_RELEASE_SPEED = 260.0   # 钩锁收到底时两球相互推开的速度（像素/秒）。
                             # 和吸住分开两个数：这两件事的节奏以后大概不会一起调
THRUST_MIN_EXIT_SPEED = 260.0  # 穿刺冲完接着走的速度下限（像素/秒）。冲刺是为了
                               # 位移，不是为了永久提速：出手时本来就慢（刚被吸慢、
                               # 正要停下），冲完不该比出手时还慢，所以兜一个底

DEBUG_VELOCITY_SCALE = 0.25  # 调试视图里动量箭头的长度缩放（380px/s → 95px）

# ---------------- 字体 ----------------
FONT_SMALL = 15
FONT_BODY = 19
FONT_TITLE = 22
FONT_BIG = 40

# 右栏（角色选择）单独一套小字。它跟左栏、底栏不共用，因为只有它需要
# "同时摆很多张卡"——把通用字号调小会连带把别处也改小。
FONT_RIGHT_TITLE = 17        # "角色"两个字
FONT_CARD_NAME = 15          # 卡片上的角色名
FONT_CARD_DESC = 12          # 卡片上的说明小字
FONT_HINT = 12               # 面板底部的操作提示

# ---------------- 配色 ----------------
COLOR_BG = (14, 16, 22)
COLOR_PANEL = (22, 25, 34)
COLOR_PANEL_BORDER = (44, 50, 66)
COLOR_PANEL_TITLE = (128, 138, 160)

COLOR_ARENA_FILL = (28, 32, 44)
COLOR_ARENA_BORDER = (86, 96, 120)

COLOR_BUTTON = (40, 46, 60)
COLOR_BUTTON_HOVER = (56, 64, 84)
COLOR_BUTTON_ACTIVE = (52, 108, 168)
COLOR_BUTTON_DISABLED = (26, 29, 38)
COLOR_BUTTON_BORDER = (58, 66, 86)
COLOR_BUTTON_TEXT = (214, 222, 238)
COLOR_BUTTON_TEXT_DISABLED = (80, 86, 102)

COLOR_TEXT = (140, 150, 172)
COLOR_TEXT_DIM = (96, 104, 124)

COLOR_DEBUG_BOX = (110, 220, 140)
COLOR_DEBUG_VECTOR = (255, 206, 84)
COLOR_LATCH = (226, 122, 196)          # 吸住的那一对：连线 + 倒计时。不是调试专用，
                                       # 平时也画——吸住的吸取没有别的界面能看出来

COLOR_AURA_FILL = (150, 70, 190)       # 范围光环的填充（绘制时再去叠透明度）
COLOR_AURA_RING = (198, 120, 236)      # 范围光环的描边

COLOR_HOOK = (232, 226, 200)           # 钩尖那一点
COLOR_HOOK_ROPE = (188, 168, 128)      # 钩锁的绳子（从渔夫沿折线到钩尖）
HOOK_RADIUS = 6                        # 钩尖画多大（纯视觉，命中判定用的是对方半径）

COLOR_BEAM = (255, 96, 128)            # 激光那条线。用的是偏红的亮色，
                                       # 和扣血红字同色系——看见它就知道要掉血
COLOR_BEAM_CORE = (255, 208, 216)      # 线的芯，画得比外层细、比外层亮
BEAM_WIDTH = 5                         # 激光外边宽（像素）
BEAM_CORE_WIDTH = 2                    # 激光芯的宽度
BEAM_GLOW_WIDTH = 13                   # 画在最底下的那层光晕，压得很淡
COLOR_BEAM_GLOW = (255, 70, 110)
COLOR_LASER_NODE = (255, 170, 186)     # 墙面上的位点。攒着待连的那个画大一圈
LASER_NODE_RADIUS = 5

COLOR_BLADE = (214, 226, 244)          # 绕身刀。冷白的刃，和红色的激光拉开距离
COLOR_BLADE_EDGE = (255, 255, 255)     # 刃上那一条高光，画得比刃身细
BLADE_WIDTH = 4                        # 刃身宽度（像素）
BLADE_EDGE_WIDTH = 1                   # 高光宽度
BLADE_HUB_RADIUS = 3                   # 刀根那个小圆点，把刃和球连起来才不像飘着

COLOR_THRUST = (120, 226, 255)         # 穿刺的拖尾。青蓝色，和别的特效都不撞色
THRUST_TRAIL_WIDTH = 6                 # 拖尾根部的宽度（像素），往尾部收到 0
THRUST_TRAIL_LENGTH = 90.0             # 拖尾最长拖多长（像素）

# 黑夜降临的黑屏。整段多长是技能自己的 duration（那是节奏，属于数值），
# 这里只管"黑得快还是慢"的形状：渐暗 / 全黑 / 渐亮各占整段的比例，三个加起来是 1。
# 换位卡在渐暗走完的那一瞬，所以 rise 太短会看到换位的瞬间，太长又拖沓
DARKNESS_RISE_RATIO = 0.35
DARKNESS_HOLD_RATIO = 0.20
DARKNESS_FALL_RATIO = 0.45
COLOR_NIGHT = (0, 0, 0)                # 黑屏的颜色。纯黑，压到全黑时战场完全看不见

# 幻影刺客。紫色系，和场上别的东西都不撞：激光红、刀/锤冷白、蛛丝灰白、
# 穿刺青蓝、吸住品红。它和吸住的品红最近，但那个只在两球之间连一条线
COLOR_PHANTOM = (186, 138, 255)        # 挥砍的弧光
COLOR_PHANTOM_CORE = (238, 224, 255)   # 弧光里那道更亮的芯
PHANTOM_SLASH_STEPS = 10               # 弧用几段折线拼（越多越圆，越费）
COLOR_PHANTOM_RING = (214, 176, 255)   # 闪现那一下套在身上的那个圈
BLINK_SWING_SPEED = 9.0                # 挥砍动画每游戏秒转多少弧度。纯演出
PHANTOM_SLASH_SPREAD = 1.1             # 一刀扫过的半张角（弧度）。约 63°
PHANTOM_SLASH_WIDTH = 4                # 弧光粗细
PHANTOM_RING_PADDING = 7               # 闪现那个圈比球面大多少

# 屏幕边缘压暗（暗角）。刺客闪现那一下用；以后别的"大动作"也能用。
# 做法是先把渐变做小再放大——逐像素铺满 600×600 太慢，64×64 放大后看不出区别
VIGNETTE_BUILD_SIZE = 64               # 渐变先在这么小的图上算
VIGNETTE_INNER = 0.30                  # 中心多大一圈完全不受影响（占半宽的比例）
VIGNETTE_MAX_ALPHA = 240               # 强度 1 时四角压到多黑
COLOR_VIGNETTE = (0, 0, 0)

COLOR_HAMMER_SHAFT = (176, 132, 92)    # 大锤的柄。木色，和场上所有"光"类的东西
                                       # （激光的红、刀的冷白、丝的灰白）分开：
                                       # 它不是能量，是一根木头杆子
COLOR_HAMMER_HEAD = (196, 204, 220)    # 锤头。冷铁色，比柄亮、比刀暗
COLOR_HAMMER_HEAD_EDGE = (255, 255, 255)  # 锤头上那一条高光
HAMMER_SHAFT_WIDTH = 5                 # 柄宽（像素）。比刀粗——它是个重东西
HAMMER_HEAD_EDGE_WIDTH = 2             # 高光宽度
HAMMER_SPEED_REFERENCE = 900.0         # 技能条满格的参考锤头速度（像素/秒）。
                                       # 只是观感上的刻度，不影响任何判定：
                                       # 伤害是相对速度的平方，这个数是给玩家看
                                       # "现在这一锤有多重"的

COLOR_WEB = (216, 224, 236)            # 蛛丝。偏冷的灰白，和激光的红、刀的冷白都不同：
                                       # 它不是光，是一根绷着的线，所以不画光晕
COLOR_WEB_ANCHOR = (255, 255, 255)     # 钉在墙上的那个锚点
WEB_WIDTH = 2                          # 丝的宽度（像素）。比激光细——不封顶，会很多根
WEB_ANCHOR_RADIUS = 3                  # 锚点画多大

# ---------------- 特效 ----------------
# 镜头抖动。用"创伤值"模型：每次受击往上加 trauma（封顶 1.0），之后线性衰减，
# 实际位移取 trauma 的**平方**——平方是为了让尾巴收得干脆一点，线性位移配线性衰减
# 会一直小幅晃，看着很烦。
SHAKE_MAX_OFFSET = 7.0        # 创伤值满格时的最大位移（像素）
SHAKE_DECAY = 1.7             # 创伤值每秒衰减多少（约 0.6 秒从满格归零）
SHAKE_ON_IMPACT = 0.45        # 球撞球的基础创伤
SHAKE_ON_BOUNCE = 0.07        # 撞墙的基础创伤
SHAKE_DAMAGE_REFERENCE = 120.0  # 撞出这么多伤害时创伤翻倍（再多就封顶了）

# 碰撞圆环：撞上的一瞬间在碰撞点炸开一个"越变越大、越变越淡"的圆
RING_LIFETIME = 0.40          # 存活秒数
RING_WIDTH = 3                # 线宽（像素）
RING_RADIUS_BASE = 12.0       # 起始半径（像素）
RING_RADIUS_PER_SQRT_DAMAGE = 4.0  # 按伤害的平方根放大，免得大伤害时圈大到糊住战场
RING_RADIUS_MAX = 52.0        # 半径上限
WALL_RING_LIFETIME = 0.30     # 撞墙的圆短一点、小一点，不然满屏都是圈
WALL_RING_RADIUS = 26.0
WALL_RING_SPEED_REFERENCE = 400.0  # 撞墙速度到这个数，圈就是满尺寸

# 扣血数字
DAMAGE_NUMBER_FONT = 26       # 字号。比正文大不少，战场上一眼能看清
DAMAGE_NUMBER_LIFETIME = 1.30 # 存活秒数
DAMAGE_NUMBER_RISE = 62.0     # 总共往上飘多少像素（见 effects.py 里对这个数的用法）
DAMAGE_NUMBER_DRAG = 4.0      # 上浮的减速，越大越快停住
DAMAGE_NUMBER_INTERVAL = 0.45 # 持续伤害（吸血）每积累这么久才报一个数字。
                              # 不攒的话每秒会冒出 60 个，糊成一片
DAMAGE_NUMBER_SETTLE = 0.18   # 吸血停了之后，攒着的那点零头过这么久补报出来
COLOR_IMPACT = (255, 236, 190)  # 球撞球那个圆的颜色

# 持续伤害 / 回血的数字颜色。吸血会同时产生这两种数字：被吸的一方在掉血（红），
# 吸人的一方在回血（绿）。两边都不跟队色走——红绿一眼就能和"撞击掉血"（队色）分开。
COLOR_DOT_TEXT = (255, 96, 96)      # 持续伤害（被吸掉的血）
COLOR_HEAL_TEXT = (104, 232, 140)   # 回血（吸回来的血）

# 进度条（血条 / 技能条）。填充色统一压暗一档，好让压在上面的浅色文字读得清。
COLOR_BAR_BACK = (30, 34, 44)
COLOR_BAR_BORDER = (58, 66, 86)

# 技能条按状态换色，颜色的走向本身也是信息：蓝条增长 = 冷却在推进，
# 黄条下降 = 技能还剩多久结束。
COLOR_SKILL_READY = (44, 132, 94)      # 待发（满条）
COLOR_SKILL_ACTIVE = (214, 172, 48)    # 黄条：技能生效中，随剩余时长**下降**
COLOR_SKILL_COOLDOWN = (52, 112, 196)  # 蓝条：冷却中，随冷却推进**增长**
COLOR_SKILL_SILENCED = (150, 74, 196)  # 被沉默：还是那根冷却条，只是染紫了。
                                       # 沉默没有时长，所以条画的仍是冷却进度，
                                       # 紫色只表示"按了也没用"
BAR_TEXT = (238, 242, 250)
BAR_FILL_MUTE = 0.62                   # 血条用队色压暗后的颜色

COLOR_WINNER = (245, 224, 150)

# 两位玩家的队色。颜色属于"玩家"而不是"角色"，所以双方选同一个角色也能分清谁是谁。
PLAYER_NAMES = ("P1", "P2")
PLAYER_COLORS = [
    (64, 196, 255),   # P1 蓝
    (255, 122, 89),   # P2 橙
]
