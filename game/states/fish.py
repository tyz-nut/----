"""渔夫没钩到人时放出来的那条鱼。

## 它为什么是一条"状态"而不是一颗"球"

骑士是一颗完整的球（进 Match.units，会被激光蛛丝打到、撞墙会弹），鱼**不是**。
两者的区别在"它算不算场上的一个东西"：

- 骑士是**兵**：站得住、会累加、能替国王挡刀，所以它得是一个作战单位。
- 鱼是**一发东西**：从钩子那儿放出来、追着人咬一口就没了，它不站场、不挨打、
  不受减速。和钩锁本身是同一类——挂在渔夫身上的一条状态（ball.fishes），
  由 Match 每帧推着走。

不过它和钩锁有一处关键的不一样：**钩锁是"技能还在生效"的标记，鱼不是**。
鱼一放出来技能就收招了（用户定的"召出鱼之后技能就可以进入冷却了"），冷却从
那一刻开始走。所以鱼是账本里的一条（和激光的线、蛛丝、毒刺同类，见
Ball.fishes），而不是"这个球现在正忙"——水里同时游着几条鱼完全正常。

把它做成球的话，它会自动进入碰撞结算、光环、激光那一整套，而"一口咬完就消失"
这个前提和那些机制的每一条都要重新谈一次（被网住算不算？被锤飞算不算？），
换来的却是玩家根本看不见的东西。

## 大小

**大小是随机的，伤害和持续时间都按大小算**（用户定的）。所以一条鱼身上烤着
三样和体型挂钩的数：radius、damage、remaining。大鱼咬得重、活得也久，小鱼
扑一下就没——一次甩钩的收益因此是浮动的，这是这个技能的手感来源。

数值在召唤的那一刻由 Match.cast_fish 算好烤进来（同 WebAnchor / GoStone）：
之后再改角色参数，不会把水里已经游着的那条鱼一起改掉。

## 追踪

每帧朝**最近的敌人**转一个有限的角度（turn_rate），不是直接把速度掰过去。
所以它是"游过去咬"而不是"贴脸吸附"：转得有上限，拐急弯要先绕一个弧。而且
**拐弯的时候它会慢下来**（turn_slow）——这一条不是手感，是它能不能咬到人的
前提，理由写在 steer 里：恒速加上转角上限等于一个固定的转弯半径，那个半径
一旦比咬合距离大，鱼就只会绕着敌人画圈，永远咬不着。

所以它是一发**会自己找人的快弹**：游速比场上的球都快，一放出来就直线扑上去，
但绕急弯的时候会掉速（掉到一成四），而且限时（按体型算）——对方拖得住这几秒
就白放了。甩掉它的办法是急转弯绕它、把这几秒耗掉，不是直线跑（直线跑不过它）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pygame.math import Vector2


@dataclass
class Fish:
    """一条正在追人的鱼。"""

    position: Vector2
    velocity: Vector2
    radius: float          # 体型。画出来多大、咬多重都由它在召唤时算好了
    damage: float          # 咬中一次掉多少血（按体型烤好）
    remaining: float       # 还能活几秒（按体型烤好）
    total: float           # 出生时一共几秒，画进度用
    speed: float           # 直线游速（像素/秒）。拐弯的时候会比这个慢，见 steer
    turn_rate: float       # 每秒最多转多少弧度
    turn_slow: float       # 满舵转弯时速度打几折掉（0.8 = 只剩两成）

    @property
    def life_ratio(self) -> float:
        """还剩几成活头，1 → 0。"""
        return max(0.0, min(1.0, self.remaining / self.total)) if self.total > 0 else 0.0

    @property
    def turn_radius(self) -> float:
        """满舵时的转弯半径。见 steer 里为什么它必须比咬合距离小。"""
        if self.turn_rate <= 1e-9:
            return float("inf")
        return self.speed * (1.0 - self.turn_slow) / self.turn_rate

    def steer(self, target: Vector2, dt: float) -> None:
        """朝 target 转一个不超过 turn_rate*dt 的角度，然后游一步。

        角度差要先折到 [-π, π]：直接相减的话，从 179° 转到 -179° 会被算成
        转了 358°，鱼会在原地绕一个大圈才肯往目标那边去。

        **拐弯的时候要减速**，这不是手感问题，是"咬不咬得到"的问题：恒速加上
        转角上限，等于这条鱼有一个**固定的转弯半径** speed/turn_rate。半径比
        咬合距离（鱼的半径 + 敌人半径）大的话，它就只会绕着敌人画圈，永远咬
        不着——它转得再准也没用，因为圆上的每一点离目标都一样远。把满舵时的
        速度压下来，转弯半径就跟着缩到咬合距离以内，它才真的能一头扎进去。
        所以 turn_slow 不是"好不好看"，它是让这个技能**能收效**的那个旋钮。
        """
        offset = target - self.position
        if offset.length_squared() <= 1e-12:
            return
        want = math.atan2(offset.y, offset.x)
        now = math.atan2(self.velocity.y, self.velocity.x)
        delta = (want - now + math.pi) % math.tau - math.pi
        limit = self.turn_rate * dt
        if limit > 1e-12:
            # 舵打了几成：直线追击时是 0，原地掉头时是 1
            rudder = min(1.0, abs(delta) / limit)
            delta = max(-limit, min(limit, delta))
            speed = self.speed * (1.0 - self.turn_slow * rudder)
        else:
            speed = self.speed
        angle = now + delta
        self.velocity = Vector2(math.cos(angle), math.sin(angle)) * speed
        self.position += self.velocity * dt
