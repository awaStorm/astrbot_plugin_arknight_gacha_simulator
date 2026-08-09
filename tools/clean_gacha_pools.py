"""
卡池信息API来源清洗.py -> clean_gacha_pools.py (v3)
功能：从 PRTS API 返回的原始 JSON（存于 data/raw/gacha_wikitext.json）中提取并清洗卡池数据
输出：结构化的 data/processed/cleaned_pools.json

解析策略：
1. 直接 json.loads 原始内容（自动处理 unicode 转义）
2. 提取 wikitext 字段
3. 按分区（section）拆分
4. 在每个分区内解析 wiki 表格，按行列提取数据
5. 根据表格列位置判断 6星/5星
"""

import json
import re
from datetime import datetime
from collections import Counter


def extract_wikitext(raw_content):
    """从 PRTS API JSON 响应中提取 wikitext"""
    try:
        data = json.loads(raw_content)
        wikitext = data.get('parse', {}).get('wikitext', {}).get('*', '')
        if wikitext:
            return wikitext
    except json.JSONDecodeError:
        pass
    match = re.search(r'"\*"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_content)
    if match:
        return json.loads('"' + match.group(1) + '"')
    return raw_content


def split_sections(wikitext):
    """按 ==字段标题== 分割为分区"""
    sections = {}
    current_name = '__前言__'
    current_parts = []
    for line in wikitext.split('\n'):
        m = re.match(r'^==(.+?)==\s*$', line)
        if m:
            if current_parts:
                sections[current_name] = '\n'.join(current_parts)
            current_name = m.group(1).strip()
            current_parts = []
        else:
            current_parts.append(line)
    if current_parts:
        sections[current_name] = '\n'.join(current_parts)
    return sections


def extract_tables(text):
    """提取 wiki 表格，深度追踪正确处理嵌套"""
    tables = []
    depth = 0
    current = []
    for line in text.split('\n'):
        opens = line.count('{|')
        closes = line.count('|}')
        if opens > 0:
            if depth == 0:
                current = [line]
            else:
                current.append(line)
            depth += opens
            # 处理一行内同时有 open 和 close 的情况（如 {|...|})
            depth -= closes
        elif closes > 0:
            current.append(line)
            depth -= closes
            if depth <= 0:
                if current:
                    tables.append('\n'.join(current))
                current = []
                depth = 0
        elif depth > 0:
            current.append(line)
    if current:
        tables.append('\n'.join(current))
    return tables


def parse_row_cells(row_text):
    """将 wikitable 行文本按 | 分割为单元格列表"""
    text = re.sub(r'^\s*\|-\s*', '', row_text).strip()
    if not text:
        return []

    # 按 \n| 分割单元格，排除 \n|- 和 \n|}
    cells = re.split(r'\n\|(?!-|\})', text)
    cells = [c.strip() for c in cells if c.strip()]

    cleaned = []
    for c in cells:
        c = re.sub(r'^\|', '', c).strip()
        if c:
            cleaned.append(c)
    return cleaned


def extract_field_from_cell(cell_text, field_type):
    """
    从 wiki 单元格文本中提取信息
    field_type: 'name' / 'time' / 'ops_6' / 'ops_5'
    """
    if field_type == 'name':
        # 1) 去掉图片链接（File:/文件: 均可，含缩略图参数如 |400px|link=xxx）
        #    例如 [[File:专属推荐干员寻访.png|400px|link=寻访模拟/专属推荐干员寻访]]
        text = re.sub(r'\[\[\s*(?:文件|File)\s*:[^\]\n]*?\]\]', '', cell_text, flags=re.IGNORECASE)
        # 2) 提取内链显示名，优先取 [[目标|显示名]] 的显示名
        links = re.findall(r'\[\[([^\[\]\n]+?)\]\]', text)
        for link in links:
            # 分离目标与显示名；若带缩略图残留 (400px|link=) 也一并处理
            if '|' in link:
                target, display = link.split('|', 1)
            else:
                target, display = link, link
            display = display.strip()
            if not display or display.startswith(('文件:', 'File:')):
                continue
            # 剥离 link= 前缀残留（如 link=寻访模拟/xxx）
            if display.lower().startswith('link='):
                display = display[5:].strip()
            # 剥离缩略图尺寸前缀（如 400px）
            display = re.sub(r'^\s*\d+px\s*', '', display)
            # 去掉寻访模拟/ 页面前缀，保留卡池显示名
            display = re.sub(r'^寻访模拟[/／]?', '', display).strip()
            if not display:
                continue
            if any(display.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                continue
            # 清理 HTML 标签
            clean = re.sub(r'<[^>]+>', '', display).strip()
            if clean:
                return clean
        return None

    elif field_type == 'time':
        dates = re.findall(r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2})', cell_text)
        if len(dates) >= 2:
            return dates[0].replace('/', '-'), dates[1].replace('/', '-')
        elif len(dates) == 1:
            return dates[0].replace('/', '-'), None
        return None, None

    elif field_type in ('ops_6', 'ops_5'):
        operators = []
        for m in re.finditer(r'\{\{\s*(?:干员)?头像\s*\|\s*([^|}]+?)(?:\s*\|\s*([^}]*?))?\}\}', cell_text):
            name = m.group(1).strip()
            params = m.group(2) or ''
            entry = {'name': name, 'shop': False, 'limited': False}
            if re.search(r'\bshop\d?\s*=\s*1', params):
                entry['shop'] = True
            if re.search(r'\blimited\s*=\s*1', params):
                entry['limited'] = True
            operators.append(entry)
        return operators if operators else None

    return None


def extract_ops_from_cell_text(cell_text):
    """从任意文本中提取所有干员头像"""
    operators = []
    for m in re.finditer(r'\{\{\s*(?:干员)?头像\s*\|\s*([^|}]+?)(?:\s*\|\s*([^}]*?))?\}\}', cell_text):
        name = m.group(1).strip()
        params = m.group(2) or ''
        entry = {'name': name, 'shop': False, 'limited': False}
        if re.search(r'\bshop\d?\s*=\s*1', params):
            entry['shop'] = True
        if re.search(r'\blimited\s*=\s*1', params):
            entry['limited'] = True
        operators.append(entry)
    return operators


def process_time_range(cell_text):
    """从文本中提取起止时间"""
    text = cell_text.replace('~', '~').replace('<br/>', ' ')
    dates = re.findall(r'(\d{4}[-/]\d{2}[-/]\d{2})\s+(\d{2}:\d{2})', text)
    if len(dates) >= 2:
        t1 = f"{dates[0][0].replace('/', '-')} {dates[0][1]}"
        t2 = f"{dates[1][0].replace('/', '-')} {dates[1][1]}"
        return t1, t2
    return None, None


def get_pool_display_name(pool_name, pool_type_id, pool_number):
    """获取标准化的卡池显示名"""
    if pool_name:
        return pool_name
    if pool_type_id == 'NORM' and pool_number:
        return f"常驻标准寻访{pool_number}"
    if pool_type_id in ('CLASSIC', 'CLASSIC_ATTAIN') and pool_number:
        return f"中坚干员轮换{pool_number}"
    return '未命名卡池'


def classify_by_section_and_name(section_name, pool_name, row_text, cells):
    """根据分区和卡池名判断卡池类型"""
    # 先按分区确定大类
    if '新人' in section_name:
        return 'BOOT', '新人特惠寻访'

    if '中坚' in section_name:
        if '甄选' in row_text[:300] or '可甄选' in row_text:
            return 'CLASSIC_SELECTION', '常驻中坚寻访&中坚甄选'
        return 'CLASSIC', '常驻中坚寻访&中坚甄选'

    if '限时' in section_name:
        # 从完整的row_text或pool_name检测
        full_text = row_text
        
        # 定向甄选
        if '定向甄选' in full_text:
            return 'SPECIAL', '限时寻访'

        # 检查联合行动
        if '联合行动' in full_text:
            return 'DOUBLE', '限时寻访'
        
        # 从方括号标记判断（例如 【限定寻访·庆典】/【限定寻访·夏季】/【联动】）
        # 注意: 关键词可出现在方括号内任意位置（如 【限定寻访·夏季】 的"限定"在开头、
        # "夏季"在末尾），因此不能假设关键词紧邻右括号。
        bracket_match = re.search(r'【[^】]*(?:限定|庆典|春节|联动)[^】]*】', full_text)
        if bracket_match:
            bracket_content = bracket_match.group()
            if '联动' in bracket_content:
                return 'LINKAGE', '限时寻访'
            else:
                return 'LIMITED', '限时寻访'

        # 没有方括号标记时从池名判断
        # 从池名或文本中判断跨年欢庆
        if '跨年欢庆' in full_text:
            # 判断是否为 跨年欢庆·中坚
            if '中坚' in full_text:
                return 'CLASSIC_ATTAIN', '常驻中坚寻访&中坚甄选'
            return 'ATTAIN', '限时寻访'
        
        # 检查是否为联动（*限定干员 标记）
        if '限定干员' in full_text and '仅在' in full_text and len(re.findall(r'limited=1', full_text)) >= 1:
            return 'LINKAGE', '限时寻访'
        
        # 检查是否有"寻访池内只有以上"（联合行动标记）
        if '寻访池内只有' in full_text or '只有以上' in full_text:
            return 'DOUBLE', '限时寻访'
        
        return 'SINGLE', '限时寻访'

    if '标准' in section_name:
        return 'NORM', '常驻标准寻访'

    return 'UNKNOWN', section_name


def extract_ops_by_star(cells, section_name, row_text):
    """按表格列位置区分6星和5星干员"""
    ops_6, ops_5 = [], []

    if '中坚' in section_name and '甄选' not in section_name:
        if len(cells) >= 4:
            ops_6 = extract_field_from_cell(cells[3], 'ops_6') or []
            if len(cells) >= 5:
                ops_5 = extract_field_from_cell(cells[4], 'ops_5') or []
        return ops_6, ops_5

    elif '中坚' in section_name and '甄选' in section_name:
        # 甄选池 - 从完整文本中提取所有干员
        all_ops = extract_ops_from_cell_text(row_text)
        if all_ops:
            # 甄选池的干员都是可选的，不严格分6/5星
            # 但根据表格列名，"可甄选6★干员"和"可甄选5★干员"是分开的
            # 我们先全部放到operators_6中，标记为可选
            ops_6 = all_ops
        return ops_6, ops_5

    elif '标准' in section_name:
        if len(cells) >= 4:
            ops_6 = extract_field_from_cell(cells[3], 'ops_6') or []
            if len(cells) >= 5:
                ops_5 = extract_field_from_cell(cells[4], 'ops_5') or []
        return ops_6, ops_5

    elif '限时' in section_name:
        # 限时寻访：第3列是6星，第4列是5星
        if len(cells) >= 3:
            ops_6 = extract_field_from_cell(cells[2], 'ops_6') or []
            if len(cells) >= 4:
                ops_5 = extract_field_from_cell(cells[3], 'ops_5') or []
        return ops_6, ops_5

    elif '新人' in section_name:
        if len(cells) >= 3:
            ops_6 = extract_field_from_cell(cells[2], 'ops_6') or []
            if len(cells) >= 4:
                ops_5 = extract_field_from_cell(cells[3], 'ops_5') or []
        return ops_6, ops_5

    return ops_6, ops_5


def split_outer_rows(table_text):
    """
    按外层 |- 分割表格行，正确处理嵌套表格内部的 |-
    外层 |- 的 depth=1（外层的第一个层级），嵌套内 depth>=2
    """
    rows = []
    current = []
    depth = 0

    for line in table_text.split('\n'):
        opens = line.count('{|')
        closes = line.count('|}')
        depth += opens - closes

        if depth == 1 and line.strip().startswith('|-') and current:
            rows.append('\n'.join(current))
            current = []
        else:
            current.append(line)

    if current:
        rows.append('\n'.join(current))

    return rows


def parse_section(section_name, section_text):
    """解析一个分区下的所有表格，返回卡池列表"""
    pools = []
    tables = extract_tables(section_text)

    for table in tables:
        rows = split_outer_rows(table)
        for row_text in rows:
            row_text = row_text.strip()
            if not row_text or row_text.startswith('!'):
                continue

            # 跳过纯嵌套表格（没有外部行标记的）
            if row_text.startswith('{|'):
                continue

            cells = parse_row_cells(row_text)
            if len(cells) < 2:
                continue

            # === 第1步：先确定池子类型 ===
            pool_type_id, section_cat = classify_by_section_and_name(
                section_name, None, row_text, cells
            )

            # === 第2步：根据 pool_type_id 选择列位置 ===
            is_standard = pool_type_id in ('NORM', 'CLASSIC')
            is_timed_limited = pool_type_id in ('SINGLE', 'DOUBLE', 'LIMITED', 'LINKAGE')
            is_special = pool_type_id in ('SPECIAL', 'ATTAIN', 'CLASSIC_ATTAIN')
            is_selection = pool_type_id == 'CLASSIC_SELECTION'

            # 时间列
            time_start, time_end = None, None
            if is_standard:
                if len(cells) > 2:
                    time_start, time_end = process_time_range(cells[2])
            else:
                if len(cells) > 1:
                    time_start, time_end = process_time_range(cells[1])

            if not time_start:
                continue

            # 池名列
            pool_name = None
            if is_standard:
                if len(cells) > 1:
                    pool_name = extract_field_from_cell(cells[1], 'name')
            else:
                if cells:
                    pool_name = extract_field_from_cell(cells[0], 'name')

            # 干员列
            ops_6, ops_5 = [], []
            if is_standard:
                if len(cells) >= 4:
                    ops_6 = extract_field_from_cell(cells[3], 'ops_6') or []
                    if len(cells) >= 5:
                        ops_5 = extract_field_from_cell(cells[4], 'ops_5') or []
            elif is_selection:
                all_ops = extract_ops_from_cell_text(row_text)
                ops_6 = all_ops if all_ops else []
            elif is_special:
                # 定向甄选/跨年欢庆：operators在嵌套表格中，从整行提取
                all_ops = extract_ops_from_cell_text(row_text)
                if all_ops:
                    ops_6 = all_ops
            else:
                if len(cells) >= 3:
                    ops_6 = extract_field_from_cell(cells[2], 'ops_6') or []
                    if len(cells) >= 4:
                        ops_5 = extract_field_from_cell(cells[3], 'ops_5') or []

            # 编号（仅标准/中坚有编号）
            pool_number = None
            if is_standard:
                m = re.match(r'^(\d+)', cells[0].strip())
                if m:
                    pool_number = int(m.group(1))

            display_name = get_pool_display_name(pool_name, pool_type_id, pool_number)

            pool = {
                'pool_id': 0,
                'pool_name': display_name,
                'section': section_cat,
                'pool_type_id': pool_type_id,
                'pool_number': pool_number,
                'is_selection': is_selection,
                'time_start': time_start,
                'time_end': time_end,
                'operators_6': ops_6 if ops_6 else [],
                'operators_5': ops_5 if ops_5 else [],
            }
            # 跨年欢庆·中坚（在限时表格里），补充嵌套表格的干员数据
            if pool_type_id == 'CLASSIC_ATTAIN' and not ops_6 and not ops_5:
                all_ops = extract_ops_from_cell_text(row_text)
                if all_ops:
                    pool['operators_6'] = all_ops
            pools.append(pool)

    return pools


def clean_prts_data(raw_file_path, output_file_path):
    """主清洗流程"""
    print("=" * 60)
    print("  PRTS 卡池数据清洗工具 v3")
    print("=" * 60)

    # 1. 读取原始数据
    print(f"\n>> 读取原始数据: {raw_file_path}")
    with open(raw_file_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()
    print(f"   原始大小: {len(raw_content)} 字符")

    # 2. 从 JSON API 响应中提取 wikitext
    print(f"\n>> 提取 wikitext...")
    wikitext = extract_wikitext(raw_content)
    print(f"   Wikitext 大小: {len(wikitext)} 字符")

    # 3. 按分区拆分
    print(f"\n>> 按分区拆分...")
    sections = split_sections(wikitext)
    section_names = [k for k in sections.keys() if not k.startswith('__')]
    print(f"   找到分区: {section_names}")

    # 4. 解析每个分区
    all_pools = []
    pool_id = 1
    for sec_name, sec_text in sections.items():
        if sec_name.startswith('__'):
            continue
        print(f"\n>> 解析分区: [{sec_name}]")
        pools = parse_section(sec_name, sec_text)
        for p in pools:
            p['pool_id'] = pool_id
            pool_id += 1
            all_pools.append(p)
        print(f"   提取到 {len(pools)} 个卡池")

    # 5. 输出
    print(f"\n{'=' * 60}")
    print(f">> 清洗完成！共提取 {len(all_pools)} 个卡池数据")
    print(f"{'=' * 60}")

    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(all_pools, f, ensure_ascii=False, indent=2)
    print(f">> 已保存至: {output_file_path}")

    # 统计
    type_counts = Counter(p['pool_type_id'] for p in all_pools)
    print(f"\n>> 各类型数量:")
    for t, c in type_counts.most_common():
        print(f"   {t}: {c}")

    # 预览前10个
    print(f"\n>> 预览:")
    for p in all_pools[:10]:
        ops_6 = [o['name'] for o in p.get('operators_6', [])]
        ops_5 = [o['name'] for o in p.get('operators_5', [])]
        shop_6 = [o['name'] for o in p.get('operators_6', []) if o.get('shop')]
        print(f"   [{p['pool_id']}] {p['pool_name']} ({p['pool_type_id']})")
        print(f"       时间: {p.get('time_start', '?')} ~ {p.get('time_end', '?')}")
        if ops_6:
            print(f"       6星: {', '.join(ops_6)}")
        if shop_6:
            print(f"       进店: {', '.join(shop_6)}")
        if ops_5:
            print(f"       5星: {', '.join(ops_5)}")

    return all_pools


if __name__ == '__main__':
    import sys
    input_file = sys.argv[1] if len(sys.argv) > 1 else '../data/raw/gacha_wikitext.json'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '../data/processed/cleaned_pools.json'

    try:
        result = clean_prts_data(input_file, output_file)
    except FileNotFoundError:
        print(f"!! 找不到文件 {input_file}")
        print("请先运行 prts卡池信息获取测试.py 获取原始数据")
    except Exception as e:
        print(f"!! 运行出错: {e}")
        import traceback
        traceback.print_exc()
