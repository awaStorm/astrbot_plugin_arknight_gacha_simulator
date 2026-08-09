"""
pool_generator.py - 脏数据池( Base Pool )生成器 + 当前卡池编号

职责:
  1. 读取 characters_raw.json，按 obtainMethod 归类生成 base_pools.json
  2. 生成 pool_rules.json (各池型特化规则配置)
  3. 读取 cleaned_pools_final.json，对比当前时间生成 active_pools.json (编号 1~N)

用法:
  python pool_generator.py                    # 一次性生成所有文件
  python pool_generator.py --base-only        # 仅生成 base_pools.json
  python pool_generator.py --active-only      # 仅生成 active_pools.json
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# --- 路径查找 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)  # Script 的父目录 = 插件根目录

# 中国时区
CST = timezone(timedelta(hours=8))


def find_file(filename: str, search_dirs: List[str]) -> Optional[str]:
    """在多个目录中查找文件"""
    for d in search_dirs:
        path = os.path.join(d, filename)
        if os.path.isfile(path):
            return path
    return None


def resolve_data_paths():
    """定位所有需要的数据文件（使用插件根目录下的 data/）"""
    chars_path = find_file("characters_raw.json", [
        os.path.join(PLUGIN_DIR, "data", "raw"),
        os.path.join(PLUGIN_DIR, "data"),
    ])
    pools_path = find_file("cleaned_pools_final.json", [
        os.path.join(PLUGIN_DIR, "data", "processed"),
    ])

    output_dir = os.path.join(PLUGIN_DIR, "data", "processed")
    os.makedirs(output_dir, exist_ok=True)

    base_out = os.path.join(output_dir, "base_pools.json")
    rules_out = os.path.join(output_dir, "pool_rules.json")
    active_out = os.path.join(output_dir, "active_pools.json")

    return chars_path, pools_path, base_out, rules_out, active_out


# ============================================================
#  第一部分: 生成 base_pools.json
# ============================================================

def load_characters(chars_path: str) -> List[dict]:
    """加载 characters_raw.json，返回干员列表"""
    with open(chars_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = raw.get("cargoquery", raw) if isinstance(raw, dict) else raw
    characters = []
    for c in entries:
        t = c.get("title", c)
        characters.append({
            "charId": t.get("charId", ""),
            "name": t.get("cn", ""),
            "rarity": int(t.get("rarity", 0)),
            "profession": t.get("profession", ""),
            "subProfession": t.get("subProfession", ""),
            "obtainMethod": t.get("obtainMethod", ""),
            "cnOnlineTime": t.get("cnOnlineTime", ""),
        })
    return characters


def build_base_pools(characters: List[dict]) -> dict:
    """
    按 obtainMethod 将干员分类到脏数据池。

    分类逻辑:
      - NORM:        obtainMethod 含 "标准寻访"
      - CLASSIC:     obtainMethod 含 "中坚寻访"
      - LIMITED_EX:  obtainMethod 含 "限定寻访"
      - LINKAGE_EX:  obtainMethod 含 "联动寻访"
      - RECRUIT:     obtainMethod 含 "公开招募" (保留供参考)

    每个池按稀有度分桶: { 2: [names], 3: [names], 4: [names], 5: [names], 6: [names] }
    rarity 映射: 1→2★, 2→3★, 3→4★, 4→5★, 5→6★
    """
    KEYWORDS = ["标准寻访", "中坚寻访", "限定寻访", "联动寻访", "公开招募"]

    # 干员基本信息记录: {name: {rarity_int, obtainMethod}}
    # 先去重 (同一干员可能重复出现，以稀有度高的为准)
    char_map = {}
    for c in characters:
        name = c["name"]
        rarity = c["rarity"]
        if name not in char_map or rarity > char_map[name]["rarity"]:
            char_map[name] = {
                "rarity": rarity,
                "obtainMethod": c["obtainMethod"],
            }

    # 初始化分桶
    pools = {kw: {2: [], 3: [], 4: [], 5: [], 6: []} for kw in KEYWORDS}

    for name, info in char_map.items():
        rarity = info["rarity"]
        method = info["obtainMethod"]
        # rarity 映射: PRTS 系统的 1=2★, 2=3★, 3=4★, 4=5★, 5=6★
        # 转为游戏星级: rarity_star = rarity + 1
        star = rarity + 1
        for kw in KEYWORDS:
            if kw in method:
                if star in pools[kw]:
                    pools[kw][star].append(name)

    # 各桶排序
    for kw in KEYWORDS:
        for star in pools[kw]:
            pools[kw][star].sort()

    # -- 构建池型映射 --
    # 每个 pool_type_id 对应的 base 池及组合方式
    pool_mapping = {
        "NORM": {
            "description": "标准寻访",
            "base_pools": ["标准寻访"],
        },
        "CLASSIC": {
            "description": "中坚寻访",
            "base_pools": ["中坚寻访"],
        },
        "SINGLE": {
            "description": "限时单UP寻访",
            "base_pools": ["标准寻访"],
            "note": "与 NORM 共用标准寻访底池",
        },
        "DOUBLE": {
            "description": "限时双UP/联合行动",
            "base_pools": ["标准寻访"],
            "note": "4个6★+6个5★等权重UP，底池为标准寻访",
        },
        "LIMITED": {
            "description": "限定寻访(庆典/春节)",
            "base_pools": ["标准寻访", "限定寻访"],
            "note": "标准池 + 当期限定干员，限定干员概率 35%",
        },
        "LINKAGE": {
            "description": "联动寻访",
            "base_pools": ["标准寻访", "联动寻访"],
            "note": "标准池 + 联动限定干员",
        },
        "SPECIAL": {
            "description": "定向甄选寻访",
            "base_pools": ["标准寻访"],
            "note": "玩家从候选列表中自选UP干员，6★限制池内容，5★仅出率提升",
        },
        "BOOT": {
            "description": "新人特惠寻访",
            "base_pools": ["标准寻访"],
            "note": "仅含早期干员子集，需进一步过滤上线时间",
        },
        "ATTAIN": {
            "description": "跨年欢庆寻访",
            "base_pools": ["标准寻访"],
            "note": "pool_contents=true: 池内仅含列出的6★，非限定常驻6★",
        },
        "CLASSIC_ATTAIN": {
            "description": "跨年欢庆·中坚寻访",
            "base_pools": ["中坚寻访"],
            "note": "pool_contents=true: 池内仅含列出的中坚6★",
        },
    }

    return {
        "source": "characters_raw.json → obtainMethod 归类",
        "pools": pools,
        "mapping": pool_mapping,
    }


# ============================================================
#  第二部分: 生成 pool_rules.json
# ============================================================

def build_pool_rules() -> dict:
    """
    池型特化规则。

    规则类型:
      - default_up_rate:  默认UP占位率 {6: 0.50, 5: 0.50}
      - counter_inherit:  保底计数器是否跨同名池继承
      - ten_pull_guarantee: 十连保底是否生效
      - pool_contents:    池内容是否受限
      - first_6star_dup_protection: 首次6星必定未持有
      - select_rules:     自选UP规则
    """
    return {
        "NORM": {
            "default_up_rate": {"6": 0.50, "5": 0.50},
            "counter_inherit": True,
            "ten_pull_guarantee": True,
            "note": "双6★UP各占25%，双5★UP平分50%",
        },
        "CLASSIC": {
            "default_up_rate": {"6": 0.50, "5": 0.50},
            "counter_inherit": True,
            "ten_pull_guarantee": True,
            "note": "与 NORM 规则相同",
        },
        "SINGLE": {
            "default_up_rate": {"6": 0.50, "5": 0.50},
            "counter_inherit": True,
            "ten_pull_guarantee": True,
            "note": "单6★UP独占50%",
        },
        "DOUBLE": {
            "default_up_rate": {"6": 0.50, "5": 0.50},
            "counter_inherit": True,
            "ten_pull_guarantee": True,
            "note": "四6★UP各占12.5%，六5★UP平分50%",
        },
        "LIMITED": {
            "default_up_rate": {"6": 0.70, "5": 0.50},
            "counter_inherit": False,
            "ten_pull_guarantee": True,
            "note": "限定+陪跑各占35%六星出率，保底计数器不继承到下一期限定池",
        },
        "LINKAGE": {
            "default_up_rate": {"6": 0.50, "5": 0.50},
            "counter_inherit": False,
            "ten_pull_guarantee": True,
            "note": "联动限定池，保底不继承",
        },
        "SPECIAL": {
            "default_up_rate": {"6": 1.00, "5": 0.50},
            "counter_inherit": True,
            "ten_pull_guarantee": True,
            "note": "自选6★出率100%(从选定集合中)，自选5★仅出率提升",
        },
        "BOOT": {
            "default_up_rate": {"6": 1.00, "5": 0.50},
            "counter_inherit": False,
            "ten_pull_guarantee": False,
            "note": "新人专属池，十连可全3★，次数用完后消失",
        },
        "ATTAIN": {
            "default_up_rate": {"6": 1.00, "5": None},
            "counter_inherit": False,
            "ten_pull_guarantee": True,
            "note": "跨年欢庆: 池内容受限(仅列出的非限定6★), 首次6★必定未持有",
        },
        "CLASSIC_ATTAIN": {
            "default_up_rate": {"6": 1.00, "5": None},
            "counter_inherit": False,
            "ten_pull_guarantee": True,
            "note": "跨年欢庆·中坚: 同ATTAIN规则，但使用中坚池",
        },
    }


# ============================================================
#  第三部分: 生成 active_pools.json
# ============================================================

def parse_time(t_str: str) -> Optional[datetime]:
    """解析 'YYYY-MM-DD HH:MM' 格式时间"""
    if not t_str:
        return None
    try:
        return datetime.strptime(t_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=CST)
    except ValueError:
        return None


def generate_active_pools(pools_path: str) -> List[dict]:
    """
    读取 cleaned_pools_final.json，找出当前时间处于开放期的卡池，
    赋予 1~N 编号，写入 active_pools.json
    """
    with open(pools_path, "r", encoding="utf-8") as f:
        all_pools = json.load(f)

    now = datetime.now(CST)
    active = []

    for p in all_pools:
        start = parse_time(p.get("time_start", ""))
        end = parse_time(p.get("time_end", ""))
        if start and end and start <= now <= end:
            active.append(p)

    # 按开始时间排序后赋予编号 1~N
    active.sort(key=lambda x: x.get("time_start", ""))

    result = []
    for idx, p in enumerate(active, start=1):
        entry = {
            "active_id": idx,
            "pool_id": p.get("pool_id"),
            "pool_name": p["pool_name"],
            "pool_type_id": p["pool_type_id"],
            "time_start": p.get("time_start", ""),
            "time_end": p.get("time_end", ""),
            "time_start_str": _format_time_display(p.get("time_start", "")),
            "time_end_str": _format_time_display(p.get("time_end", "")),
            "operators_6": p.get("operators_6", []),
            "operators_5": p.get("operators_5", []),
        }

        # 特殊池规则
        if p.get("pool_contents"):
            entry["pool_contents"] = True
        if p.get("first_6star_dup_protection"):
            entry["first_6star_dup_protection"] = True
        if p.get("select_rules"):
            entry["select_rules"] = p["select_rules"]

        result.append(entry)

    return result


def _format_time_display(t_str: str) -> str:
    """将 '2026-07-20 16:00' 转为 '07.20 16:00'"""
    if not t_str:
        return ""
    try:
        dt = datetime.strptime(t_str.strip(), "%Y-%m-%d %H:%M")
        return dt.strftime("%m.%d %H:%M")
    except ValueError:
        return t_str


# ============================================================
#  主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="脏数据池生成器")
    parser.add_argument("--base-only", action="store_true", help="仅生成 base_pools.json")
    parser.add_argument("--active-only", action="store_true", help="仅生成 active_pools.json")
    args = parser.parse_args()

    chars_path, pools_path, base_out, rules_out, active_out = resolve_data_paths()

    run_base = not args.active_only
    run_active = not args.base_only

    if run_base:
        # --- Base Pools ---
        if not chars_path:
            print("!! 未找到 characters_raw.json，跳过 base_pools 生成")
        else:
            print(f">> 加载干员数据: {chars_path}")
            characters = load_characters(chars_path)
            print(f"   共 {len(characters)} 条干员记录")

            base_data = build_base_pools(characters)

            # 统计输出
            for kw in ["标准寻访", "中坚寻访", "限定寻访", "联动寻访", "公开招募"]:
                counts = {s: len(base_data["pools"][kw][s]) for s in [2, 3, 4, 5, 6]}
                total = sum(counts.values())
                print(f"   {kw}: {total}人 "
                      f"(2★:{counts[2]} 3★:{counts[3]} 4★:{counts[4]} 5★:{counts[5]} 6★:{counts[6]})")

            with open(base_out, "w", encoding="utf-8") as f:
                json.dump(base_data, f, ensure_ascii=False, indent=2)
            print(f">> base_pools.json 已生成: {base_out}")

        # --- Pool Rules ---
        rules = build_pool_rules()
        with open(rules_out, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        print(f">> pool_rules.json 已生成: {rules_out}")

    if run_active:
        # --- Active Pools ---
        if not pools_path:
            print("!! 未找到 cleaned_pools_final.json，跳过 active_pools 生成")
        else:
            print(f">> 加载卡池数据: {pools_path}")
            active = generate_active_pools(pools_path)
            print(f"   当前进行中的卡池: {len(active)} 个")
            for a in active:
                print(f"   [#{a['active_id']}] {a['pool_name']} ({a['pool_type_id']}) "
                      f"{a['time_start_str']} ~ {a['time_end_str']}")

            with open(active_out, "w", encoding="utf-8") as f:
                json.dump(active, f, ensure_ascii=False, indent=2)
            print(f">> active_pools.json 已生成: {active_out}")

    print("\n>> 阶段一: 数据层与底座构建完成")


if __name__ == "__main__":
    main()
