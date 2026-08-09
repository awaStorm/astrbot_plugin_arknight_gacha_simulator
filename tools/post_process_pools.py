"""
post_process_pools.py
功能：
  1. 利用 characters_raw.json 的 rarity 字段，分离 SPECIAL（定向甄选）池的 6★/5★ 干员
  2. 修复 BOOT（新人特惠）池的池名
  3. 为 ATTAIN/CLASSIC_ATTAIN 添加 pool_contents 标记
输出：data/processed/cleaned_pools_final.json
"""

import json
import re
from collections import Counter


def build_rarity_map(characters_path):
    """从 characters_raw.json 构建 {干员中文名 -> rarity} 映射表"""
    with open(characters_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    items = raw.get('cargoquery', raw.get('result', []))
    rarity_map = {}

    for item in items:
        title = item.get('title', {})
        cn_name = title.get('cn', '')
        rarity_str = title.get('rarity', '')
        if cn_name and rarity_str:
            # rarity 5=6★, 4=5★
            rarity_map[cn_name] = int(rarity_str)

    return rarity_map


def rarity_to_stars(rarity):
    """将游戏 rarity 值转换为★数"""
    mapping = {5: 6, 4: 5, 3: 4, 2: 3, 1: 2, 0: 1}
    return mapping.get(rarity, 0)


def fix_boot_pool_name(pool):
    """修复新人特惠池的池名"""
    raw_name = pool.get('pool_name', '')
    # 旧格式: "400px|link=寻访模拟/专属推荐干员寻访02"
    m = re.search(r'link=寻访模拟/(.+?)(?:\||$)', raw_name)
    if m:
        display = m.group(1)
        # 去掉尾部的编号，转换为友好名称
        if '专属推荐' in display:
            pool['pool_name'] = '专属推荐干员寻访'
        else:
            pool['pool_name'] = display
    return pool


def fix_special_pool(pool, rarity_map):
    """利用 rarity_map 分离 SPECIAL 池的 6★ 和 5★ 干员"""
    all_ops = pool.get('operators_6', [])
    if not all_ops:
        return pool

    ops_6 = []
    ops_5 = []
    unknown = []

    for op in all_ops:
        name = op['name']
        rarity = rarity_map.get(name)
        stars = rarity_to_stars(rarity) if rarity is not None else 0

        entry = {'name': name, 'shop': op.get('shop', False), 'limited': op.get('limited', False)}

        if stars >= 6:
            ops_6.append(entry)
        elif stars == 5:
            ops_5.append(entry)
        elif stars > 0:
            ops_5.append(entry)  # 4星及以下也放进5星列表
        else:
            unknown.append(entry)

    pool['operators_6'] = ops_6
    pool['operators_5'] = ops_5

    if unknown:
        print(f"  [警告] {pool['pool_name']}: {len(unknown)} 个干员未找到 rarity，\
已放入 operators_unknown: {[o['name'] for o in unknown]}")
        pool['operators_unknown'] = unknown

    # 标注选择规则（纯结构化字段，供下游脚本直接使用）
    pool['select_rules'] = {
        "6star": {
            "max_select": 3,
            "pool_restricted": True,
            "dup_protection": False
        },
        "5star": {
            "max_select": 3,
            "pool_restricted": False,
            "dup_protection": False
        }
    }

    return pool


def fix_attain_pool(pool):
    """为 ATTAIN/CLASSIC_ATTAIN 添加池内容标记"""
    pool['pool_contents'] = True
    if 'select_rules' not in pool:
        pool['first_6star_dup_protection'] = True
    return pool


def post_process(input_path, characters_path, output_path):
    """主流程"""
    print("=" * 60)
    print("  卡池数据后处理脚本")
    print("=" * 60)

    # 1. 构建干员稀有度映射表
    print(f"\n>> 构建干员稀有度映射...")
    rarity_map = build_rarity_map(characters_path)
    print(f"   共 {len(rarity_map)} 个干员")

    # 验证映射覆盖度：检查 SPECIAL 池的干员是否能查到
    sample_ops = ['司霆惊蛰', '仇白', '提丰', '隐德来希', '撷英调香师', '空构', '折桠', '风絮', '裁度', '晓歌']
    miss = [n for n in sample_ops if n not in rarity_map]
    if miss:
        print(f"   [检查] 未在映射表中找到: {miss}")
    else:
        print(f"   [检查] 所有 SPECIAL 干员均可在 rarity_map 中找到")

    # 2. 读取 cleaned_pools.json
    print(f"\n>> 读取原数据: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        pools = json.load(f)
    print(f"   共 {len(pools)} 个卡池")

    # 3. 逐池修正
    stats = {'fixed_special': 0, 'fixed_boot': 0, 'tagged_attain': 0}
    for pool in pools:
        tid = pool['pool_type_id']

        if tid == 'SPECIAL':
            fix_special_pool(pool, rarity_map)
            stats['fixed_special'] += 1

        elif tid == 'BOOT':
            fix_boot_pool_name(pool)
            stats['fixed_boot'] += 1

        elif tid == 'ATTAIN':
            fix_attain_pool(pool)
            stats['tagged_attain'] += 1

        elif tid == 'CLASSIC_ATTAIN':
            fix_attain_pool(pool)
            stats['tagged_attain'] += 1

    # 4. 输出
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(pools, f, ensure_ascii=False, indent=2)

    print(f"\n>> 修正统计:")
    print(f"   SPECIAL 池 6★/5★ 分离: {stats['fixed_special']}")
    print(f"   BOOT 池名修复:         {stats['fixed_boot']}")
    print(f"   ATTAIN 标记:            {stats['tagged_attain']}")

    print(f"\n>> 已保存至: {output_path}")

    # 5. 验证 SPECIAL 池
    print(f"\n>> 验证定向甄选修正结果:")
    for p in pools:
        if p['pool_type_id'] == 'SPECIAL':
            ops_6 = [o['name'] for o in p.get('operators_6', [])]
            ops_5 = [o['name'] for o in p.get('operators_5', [])]
            print(f"   {p['pool_name']}")
            print(f"     6★ UP候选 ({len(ops_6)}): {', '.join(ops_6)}")
            print(f"     5★ UP候选 ({len(ops_5)}): {', '.join(ops_5)}")
            if 'select_rules' in p:
                print(f"     规则: 6星选{p['select_rules']['6star']['max_select']}个, \
5星选{p['select_rules']['5star']['max_select']}个")

    # 6. 验证 ATTAIN
    print(f"\n>> 验证跨年欢庆修正:")
    for p in pools:
        if p['pool_type_id'] in ('ATTAIN', 'CLASSIC_ATTAIN'):
            ops_6 = [o['name'] for o in p.get('operators_6', [])]
            print(f"   {p['pool_name']} ({p['pool_type_id']})")
            print(f"     池中6星 ({len(ops_6)}): {', '.join(ops_6[:5])}...")

    # 7. 最终统计
    print(f"\n{'=' * 60}")
    type_counts = Counter(p['pool_type_id'] for p in pools)
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"   {t}: {c}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    import sys
    input_path = sys.argv[1] if len(sys.argv) > 1 else '../data/processed/cleaned_pools.json'
    characters_path = sys.argv[2] if len(sys.argv) > 2 else '../data/raw/characters_raw.json'
    output_path = sys.argv[3] if len(sys.argv) > 3 else '../data/processed/cleaned_pools_final.json'

    try:
        post_process(input_path, characters_path, output_path)
    except FileNotFoundError as e:
        print(f"!! 找不到文件: {e}")
        print("请确保 data/raw/characters_raw.json 存在（先运行 scripts/fetch_characters.py）")
    except Exception as e:
        print(f"!! 运行出错: {e}")
        import traceback
        traceback.print_exc()
