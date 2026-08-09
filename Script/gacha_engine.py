"""
gacha_engine.py - 明日方舟抽卡概率引擎

实现权重上限轮盘选择模型 (W_ceil=10000):
  - 六星软保底递增 (第51抽起每抽+2%权重)
  - 五星权重递增 (无绝对保底)
  - UP 干员分配 (根据 pool_type_id 和 pool_rules)
  - 十连保底 (至少一个4★)
  - 计数器更新规则

用法:
  engine = GachaEngine(base_pools_path, pool_rules_path)
  result, counters = engine.single_pull(pool_type_id, ops_6, ops_5, i, j, select_rules)
  results, counters = engine.ten_pull(pool_type_id, ops_6, ops_5, i, j, select_rules)
"""

import json
import os
import random
from typing import Dict, List, Optional, Tuple


# 各星级 base 权重
WEIGHT_BASE = {6: 200, 5: 800, 4: 5000, 3: 4000}

# 权重上限
W_CEIL = 10000

# 星级优先级 (高 → 低，用于溢出裁剪)
STAR_PRIORITY = [6, 5, 4, 3]

# 默认星数排序
STARS = [6, 5, 4, 3]


class GachaEngine:
    def __init__(self, base_pools_path: str, pool_rules_path: str):
        """
        base_pools_path: base_pools.json 路径
        pool_rules_path: pool_rules.json 路径
        """
        self.base_pools = self._load_json(base_pools_path)
        self.pool_rules = self._load_json(pool_rules_path)
        self._random = random.SystemRandom()

    def _load_json(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ──────────────────── 核心算法 ────────────────────

    def _calc_weights(self, i: int, j: int) -> Dict[int, int]:
        """
        计算各星级当前权重。

        i: 六星计数器 (已连续无六星的抽数)
        j: 五星计数器 (已连续无五星/六星的抽数)

        返回 {6: w6, 5: w5, 4: 5000, 3: 4000}
        """
        # 六星权重
        if i <= 50:
            w6 = WEIGHT_BASE[6]
        else:
            w6 = WEIGHT_BASE[6] + 200 * (i - 50)

        # 五星权重
        if j <= 15:
            w5 = WEIGHT_BASE[5]
        elif j <= 20:
            w5 = WEIGHT_BASE[5] + 200 * (j - 15)
        else:
            w5 = 1800 + 400 * (j - 20)

        return {
            6: w6,
            5: w5,
            4: WEIGHT_BASE[4],
            3: WEIGHT_BASE[3],
        }

    def _resolve_rarity(self, weights: Dict[int, int]) -> int:
        """
        权重溢出裁剪 + 轮盘选择 → 返回星级 (6/5/4/3)。

        规则: 当总权重超过 W_CEIL 时，优先舍去低星级权重。
        即: 6★ > 5★ > 4★ > 3★ 的优先级顺序，低星级的超额部分先裁。
        """
        # 复制权重用于裁剪
        clipped = dict(weights)
        total = sum(clipped.values())

        if total > W_CEIL:
            excess = total - W_CEIL
            # 从低优先级(3★)开始裁，向上直到多余权重被裁完
            for star in [3, 4, 5, 6]:
                if excess <= 0:
                    break
                cut = min(clipped[star], excess)
                clipped[star] -= cut
                excess -= cut

        # 重新计算实际总权重
        total = sum(clipped.values())

        # 轮盘选择: 从高优先级到低
        roll = self._random.uniform(0, total)
        cumulative = 0
        for star in [6, 5, 4, 3]:
            cumulative += clipped[star]
            if roll < cumulative:
                return star

        # 兜底
        return 3

    def _resolve_character(
        self,
        star: int,
        pool_type_id: str,
        ops_6_ups: List[str],
        ops_5_ups: List[str],
        select_rules: Optional[dict] = None,
        owned_characters: Optional[List[str]] = None,
    ) -> Tuple[str, bool]:
        """
        确定具体干员。

        star: 命中星级
        pool_type_id: 卡池类型
        ops_6_ups: 六星UP干员名列表
        ops_5_ups: 五星UP干员名列表
        select_rules: SPECIAL/ATTAIN 的自选规则
        owned_characters: 用户已持有干员名列表 (用于 ATTAIN 首次未持有保护)

        返回 (干员名, is_up)
        """
        rules = self.pool_rules.get(pool_type_id, {})
        up_rate = rules.get("default_up_rate", {})
        pool_contents = rules.get("pool_contents", False)

        # 获取脏数据池
        mapping = self.base_pools.get("mapping", {})
        pool_entry = mapping.get(pool_type_id, {})
        base_pool_names = pool_entry.get("base_pools", [])

        # 合并所有 base_pool 中该星级的干员
        all_pool = self.base_pools.get("pools", {})
        available = []
        for bp_name in base_pool_names:
            bp = all_pool.get(bp_name, {})
            available.extend(bp.get(str(star), []))

        # 去重
        available = list(set(available))

        if not available:
            # 极端情况: 池子没有该星级的干员，降级到下一星级
            available = ["预备干员-近战"]  # fallback

        # --- 确定 UP 概率 ---
        if star == 6:
            up_rate_val = up_rate.get("6", 0.5)
            up_list = ops_6_ups
        elif star == 5:
            up_rate_val = up_rate.get("5", 0.5)
            up_list = ops_5_ups
        else:
            up_rate_val = 0
            up_list = []

        # SPECIAL 池特殊处理: 6★只从选定集合中出
        if pool_type_id == "SPECIAL" and star == 6:
            if select_rules and "6star" in select_rules:
                r = select_rules["6star"]
                if r.get("pool_restricted"):
                    # 6★只从 operators_6 列表中出 (玩家从中自选了)
                    up_list = ops_6_ups
                    up_rate_val = 1.0
                    available = list(up_list)  # 覆盖可用池

        # ATTAIN 池特殊处理: pool_contents 限制池内容
        if pool_type_id in ("ATTAIN", "CLASSIC_ATTAIN") and pool_contents:
            # 池内容受限为列出的干员
            available = list(ops_6_ups) if star == 6 else available
            up_rate_val = 1.0
            up_list = ops_6_ups if star == 6 else ops_5_ups

            # 首次6★未持有保护
            if (star == 6 and rules.get("first_6star_dup_protection")
                    and owned_characters is not None):
                unowned = [op for op in available if op not in owned_characters]
                if unowned:
                    available = unowned

        # --- UP 判定 ---
        if up_list and self._random.random() < up_rate_val:
            # 命中 UP
            chosen = self._random.choice(up_list)
            return chosen, True

        # 未命中 UP，从可用池中随机
        # 排除 UP 干员 (避免逻辑上同时命中UP和非UP)
        pool_without_up = [op for op in available if op not in up_list]
        if not pool_without_up:
            pool_without_up = available
        chosen = self._random.choice(pool_without_up)
        return chosen, False

    # ──────────────────── 核心接口 ────────────────────

    def single_pull(
        self,
        pool_type_id: str,
        ops_6_ups: List[str],
        ops_5_ups: List[str],
        i: int,
        j: int,
        select_rules: Optional[dict] = None,
        owned_characters: Optional[List[str]] = None,
        force_rarity: int = 0,
    ) -> Tuple[dict, int, int]:
        """
        单次抽卡。

        参数:
          pool_type_id: 卡池类型 (NORM/SINGLE/LIMITED...)
          ops_6_ups: 六星 UP 干员名列表
          ops_5_ups: 五星 UP 干员名列表
          i: 当前六星计数器
          j: 当前五星计数器
          select_rules: 自选规则 (SPECIAL 池)
          owned_characters: 已持有干员名列表 (ATTAIN 首次未持有保护用)
          force_rarity: >0 时跳过正常权重计算，直接从该星级池按 UP 权重随机 (用于首发10抽保底)

        返回:
          (result, new_i, new_j)
          result: {"name": str, "rarity": int, "is_up": bool}
          new_i: 更新后的六星计数器
          new_j: 更新后的五星计数器
        """
        # 1. 确定星级（首发保底时强制指定）
        if force_rarity in (5, 6):
            star = force_rarity
        else:
            weights = self._calc_weights(i, j)
            star = self._resolve_rarity(weights)

        # 2. 确定干员
        name, is_up = self._resolve_character(
            star, pool_type_id, ops_6_ups, ops_5_ups,
            select_rules, owned_characters,
        )

        # 3. 更新计数器
        if star == 6:
            new_i, new_j = 0, 0
        elif star == 5:
            new_i, new_j = i + 1, 0
        else:
            new_i, new_j = i + 1, j + 1

        return {"name": name, "rarity": star, "is_up": is_up}, new_i, new_j

    def ten_pull(
        self,
        pool_type_id: str,
        ops_6_ups: List[str],
        ops_5_ups: List[str],
        i: int,
        j: int,
        select_rules: Optional[dict] = None,
        owned_characters: Optional[List[str]] = None,
        first_ten_start: Optional[int] = None,
        first_ten_seen: bool = False,
    ) -> Tuple[List[dict], int, int]:
        """
        十连抽卡 (含保底)。

        十连保底: 若10次结果全为3★，将最后一个替换为随机4★。
        BOOT 池例外：无十连保底。

        首发十连五星保底 (计数器级): first_ten_start 为该用户该池抽卡前的累计 pull_count，
        引擎在循环内定位全局第10抽 (idx == 9 - first_ten_start)。若该抽结果 <5★
        且此前从未出过 ≥5★ (first_ten_seen=False)，则用 force_rarity=5 重新抽取，
        按池子 UP 权重随机出一个 5★ 干员，并校正计数器。

        返回:
          (results, new_i, new_j)
          results: list of {"name": str, "rarity": int, "is_up": bool}
        """
        rules = self.pool_rules.get(pool_type_id, {})
        has_ten_pull_guarantee = rules.get("ten_pull_guarantee", True)

        # 首发保底: 全局第10抽在本次十连中的位置（idx），-1 表示本次不触发
        guard_active = (
            first_ten_start is not None
            and not first_ten_seen
            and 0 <= first_ten_start <= 9
        )
        guard_idx = 9 - first_ten_start if guard_active else -1

        ci, cj = i, j
        results = []

        for idx in range(10):
            ci_prev, cj_prev = ci, cj
            result, ci, cj = self.single_pull(
                pool_type_id, ops_6_ups, ops_5_ups, ci_prev, cj_prev,
                select_rules, owned_characters,
            )

            # 首发十连五星保底: 本抽为累计第10抽 且 前9抽无≥5★ 且 本抽<5★ → 强制替换
            if guard_active and idx == guard_idx and result["rarity"] < 5:
                result, ci, cj = self.single_pull(
                    pool_type_id, ops_6_ups, ops_5_ups, ci_prev, cj_prev,
                    select_rules, owned_characters, force_rarity=5,
                )

            results.append(result)

        # ---------- 十连保底 (4★) ----------
        if has_ten_pull_guarantee:
            if all(r["rarity"] == 3 for r in results):
                mapping = self.base_pools.get("mapping", {})
                pool_entry = mapping.get(pool_type_id, {})
                base_pool_names = pool_entry.get("base_pools", [])
                all_pool = self.base_pools.get("pools", {})
                four_stars = []
                for bp_name in base_pool_names:
                    bp = all_pool.get(bp_name, {})
                    four_stars.extend(bp.get("4", []))
                four_stars = list(set(four_stars))

                if four_stars:
                    replacement = self._random.choice(four_stars)
                    results[-1] = {"name": replacement, "rarity": 4, "is_up": False}

        return results, ci, cj
