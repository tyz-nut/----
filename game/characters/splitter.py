"""分裂：撞一次裂一块，自己撞自己再合回来。

这个角色是全场唯一一个**不只有一个身子**的玩家球。它走的还是碰撞那条路
（on_collision），但主张里多了一样别处没有的东西：splits / fuses——"这一撞
把自己裂成两半"和"这一撞和对面那块合回一块"。怎么执行在 Match.split_ball /
fuse_balls，这里只负责判断**该不该**。

## 三条规则（用户定的）

- **撞上敌人：对敌人造成固定伤害，同时自己裂成两个**。伤害是固定值，不看速度、
  不看残血、也不看自己现在是第几代——所以八块小碎片各自撞一下，每一块打的都是
  同一个数。裂开只有被**别的球撞到**才发生，技能的伤害（激光、锤、穿刺）不算。
- **血量和大小各减半**，所以总血量不减：一块 500 的裂成两块 250 的，玩家那边
  一分没少。掉的是"每一块有多脆"，不是"一共有多少血"。
- **最多裂三次**，也就是最细能到第 3 代（本体的八分之一大）。
- **自己跟自己撞上就合体**，但**必须同代**：gen2 撞 gen2 合回 gen1，gen2 撞 gen3
  什么都不发生（用户定的"分裂两次的和分裂三次的碰撞没效果"）。合出来退一代，
  于是**又能再裂两次**——这是这个角色唯一能把裂散的自己重新攒大的手段。

## 为什么合体是"退一代"而不是"并成一块满血的"

因为不退的话，融合就成了纯赚：裂开不掉总量、合上再翻倍，来回几次就无限大。
退一代让"合"和"裂"变成同一件事的两个方向——**代数就是这块身板的档位**，
在它上面来回走，总量始终是角色那一个 max_hp。所以这个角色的血量尺子从头到尾
只有一把，玩家需要做的判断是"现在要一块大的还是一堆小的"，而不是"能不能滚雪球"。

## 为什么它需要 match 那一侧的配合，而不是自己搞定

因为裂开要**造一颗新球**。球从哪里来、摆在哪、速度给多少，都要问战场（Arena
才知道边界在哪）和整局（units 那张表才认身份）。角色的 on_collision 拿不到
match，这是有意的：主张就该只是一句话，"谁去执行"是 Match 的事——和抓取、
召唤骑士是同一条分工。

数值不在这里，在 game/config/roster.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Character, CollisionOutcome

if TYPE_CHECKING:
    from ..core.ball import Ball


@dataclass(frozen=True)
class Splitter(Character):
    """碰撞效果：伤敌人一笔固定的，然后自己裂开；撞到自己那一半就合回去。

    "自己那一半"是按 **player 相同** 认的，不是按"同一种角色"：两个分裂玩家
    对打时，撞上**对面**的碎片走的是"伤对方 + 自己裂开"那条，不会互相融合。
    融合只发生在同一个玩家的碎片之间。

    技能栏填的是 IdleSkill（永远不会被放出来）：这个角色的全部本事都在碰撞里，
    没有主动技能——和激光、蜘蛛、大锤、望一样。
    """

    hit_damage: float = 0.0        # 撞上敌人，对方掉这么多（固定值，不看速度）
    max_halvings: int = 3          # 最多裂几次。裂到这个代数就不再裂了
    split_speed: float = 0.0       # 两个半身散开的速度（像素/秒）

    # 同边相撞要问主张——"自己跟自己合体"就在那里。**要把父类那一栏重新写一遍
    # 才有效**：dataclass 的默认值是生成 __init__ 的时候抄进参数里的，光在类体
    # 里写一句 `same_side_collisions = True`（不带类型注解）只是挂了个类属性，
    # 构造出来还是父类那个 False，融合会一声不响地永远不触发
    same_side_collisions: bool = True

    def on_collision(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """两颗球贴上了，这一边说它想干什么。

        两边是各自独立被问的（Match 两边都问），所以两个分裂撞在一起时，两边
        各裂各的——这是对的，"被碰撞时分裂"对双方都成立。

        同边的那一支（合体）走的是另一条：什么都不伤，只提一句"我要合"。
        """
        if other.player == ball.player:
            return self._fusion(ball, other)
        return CollisionOutcome(
            damage_to_other=self.hit_damage,
            # 到顶了就不再裂，但**伤害照打**——"最多裂三次"限的是身子，不是拳头
            splits=ball.generation < self.max_halvings,
        )

    def _fusion(self, ball: Ball, other: Ball) -> CollisionOutcome:
        """该不该和对面那块合。

        三道关，缺一不可：

        - **代数要一样**（用户定的）。gen2 和 gen3 撞上什么都不发生，就是普通
          地弹开——"分裂两次的和分裂三次的碰撞没效果"。
        - **不能是本体**：generation 0 是没有兄弟的那一块，场上同一边不可能有
          两块 gen0（除非以后有第二个分身技能），但真出现了也不该凭空融合。
        - **没上锁**。刚裂开的两半本来就是摆在相切位置上的，不锁的话下一帧就
          融回原样，分裂等于没发生（见 config.FUSE_LOCK_SECONDS）。
        """
        if ball.generation <= 0 or ball.generation != other.generation:
            return CollisionOutcome()
        if ball.fuse_lock > 0.0 or other.fuse_lock > 0.0:
            return CollisionOutcome()
        return CollisionOutcome(fuses=True)
