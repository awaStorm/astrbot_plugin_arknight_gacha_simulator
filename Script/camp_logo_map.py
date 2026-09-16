# -*- coding: utf-8 -*-
"""
camp_logo_map.py - 干员阵营 → 阵营 logo 图片 映射表

数据来源：
  · 阵营中文名：PRTS `chara.logo` 字段，随 data/raw/characters_raw.json 一起加载
  · 图片文件：静态素材 gacha_primary_material/ui_camp_logo_0/logo_*.png

降级规则：
  映射未命中 / 阵营值为空 / 文件不存在 → 统一使用 DEFAULT_CAMP（罗德岛）。

已知特殊情况：
  · 「深池」与「塔拉」的图标外观相同，按正常映射处理即可，无需特殊分支。
  · 「无团队」「罗德岛-精英干员」「S.E.E.S.」按需求直接降级为罗德岛。
  · 「深池」(logo_dublinn.png) 当前无干员使用，保留映射以备后续新增干员。
"""

# 阵营 logo 所在子目录（相对 composer_config.MATERIAL_DIR，即 gacha_primary_material/）
CAMP_LOGO_DIR = "ui_camp_logo_0"

# 降级目标阵营（映射失败时使用）
DEFAULT_CAMP = "罗德岛"

# 阵营中文名 -> logo 文件名
CAMP_LOGO_MAP = {
    # ---- 主要阵营 / 国家 ----
    "罗德岛": "logo_rhodes.png",
    "炎-龙门": "logo_lungmen.png",
    "炎": "logo_yan.png",
    "炎-岁": "logo_sui.png",
    "龙门近卫局": "logo_lgd.png",
    "乌萨斯": "logo_ursus.png",
    "乌萨斯学生自治团": "logo_student.png",
    "维多利亚": "logo_victoria.png",
    "卡西米尔": "logo_kazimierz.png",
    "谢拉格": "logo_kjerag.png",
    "喀兰贸易": "logo_karlan.png",
    "莱塔尼亚": "logo_Leithanien.png",
    "拉特兰": "logo_Laterano.png",
    "伊比利亚": "logo_iberia.png",
    "叙拉古": "logo_siracusa.png",
    "哥伦比亚": "logo_columbia.png",
    "玻利瓦尔": "logo_bolivar.png",
    "米诺斯": "logo_minos.png",
    "萨尔贡": "logo_sargon.png",
    "萨米": "logo_sami.png",
    "东": "logo_higashi.png",
    "雷姆必拓": "logo_rim.png",
    "汐斯塔": "logo_siesta.png",
    "塔拉": "logo_tara.png",
    "阿戈尔": "logo_egir.png",

    # ---- 组织 / 势力 ----
    "企鹅物流": "logo_penguin.png",
    "黑钢国际": "logo_blacksteel.png",
    "莱茵生命": "logo_rhine.png",
    "巴别塔": "logo_babel.png",
    "使徒": "logo_followers.png",
    "格拉斯哥帮": "logo_glasgow.png",
    "深海猎人": "logo_abyssal.png",
    "彩虹小队": "logo_rainbow.png",
    "红松骑士团": "logo_pinus.png",
    "莱欧斯小队": "logo_laios.png",
    "鲤氏侦探事务所": "logo_lee.png",
    "贾维团伙": "logo_chiave.png",
    "Ave Mujica": "logo_mujica.png",
    "S.W.E.E.P.": "logo_sweep.png",
    "深池": "logo_dublinn.png",          # 备用：当前无干员使用

    # ---- 行动组 ----
    "行动组A4": "logo_action4.png",
    "行动预备组A1": "logo_reserve1.png",
    "行动预备组A4": "logo_reserve4.png",
    "行动预备组A6": "logo_reserve6.png",

    # ---- 按需求直接降级为罗德岛 ----
    "无团队": "logo_rhodes.png",
    "罗德岛-精英干员": "logo_rhodes.png",
    "S.E.E.S.": "logo_rhodes.png",
}


def get_camp_logo_file(camp_cn: str) -> str:
    """
    按阵营中文名取 logo 文件名（仅文件名，不含目录）。

    映射未命中或名称为空时，一律降级为 DEFAULT_CAMP（罗德岛），
    保证调用方永远拿到一个可用的文件名。
    """
    name = (camp_cn or "").strip()
    return CAMP_LOGO_MAP.get(name, CAMP_LOGO_MAP[DEFAULT_CAMP])
