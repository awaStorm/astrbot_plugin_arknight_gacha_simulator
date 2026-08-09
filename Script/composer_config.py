# -*- coding: utf-8 -*-
"""
composer_config.py - 插件实际使用的【构图参数配置块】

本文件由 Generator_test/config.py 100% 复制而来（所有图片生成逻辑与参数完全一致），
仅把静态素材路径从 Generator_test/resources/ 适配到插件实际使用的素材目录，
并移除测试专用内容（TEST_TEN_PULL / OUTPUT_PATH 等）。

素材目录对应关系：
  Generator_test/resources/backgrounds  -> 插件 gacha_primary_material/（背景/分隔条）
  Generator_test/resources/cards        -> 插件 gacha_primary_material/recruit_ten_result_state/
  Generator_test/resources/textures     -> 插件 gacha_primary_material/recruit_ten_result_state/
  Generator_test/resources/stars        -> 插件 gacha_primary_material/recruit_ten_result_state/
  Generator_test/resources/portraits    -> 插件 data/cache/portraits/（动态下载缓存）
  Generator_test/resources/professions  -> 插件 data/cache/professions/（动态下载缓存）
  Generator_test/resources/raw          -> 插件 data/raw/
"""

import os

# =============================================================================
#  0. 资源路径 (Resource Paths)
#     统一指向插件实际使用的素材目录。
# =============================================================================
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 插件根目录
MATERIAL_DIR = os.path.join(PLUGIN_DIR, "gacha_primary_material")          # 素材总目录
STATE_DIR = os.path.join(MATERIAL_DIR, "recruit_ten_result_state")         # 卡底/星级/光效/网点
CACHE_DIR = os.path.join(PLUGIN_DIR, "data", "cache")                      # 动态下载缓存总目录

# 各资源子目录（与 Generator_test config.py 的目录语义一一对应）
BG_DIR = MATERIAL_DIR              # 背景底图 / 分隔条 (16:9 / 1024x1024)
CARD_DIR = STATE_DIR               # 卡牌底框 (back_low_* / back_four / back_five)
TEXTURE_DIR = STATE_DIR            # 网点 / 纹理 / 光效贴图 (dianzhen / guangxiao 等)
STAR_DIR = STATE_DIR               # 星级标 (star_1 ~ star_6)
PROF_DIR = os.path.join(CACHE_DIR, "professions")   # 职业图标 (动态下载缓存)
PORTRAIT_DIR = os.path.join(CACHE_DIR, "portraits") # 角色半身像 / 立绘 (动态下载缓存)
RAW_DIR = os.path.join(PLUGIN_DIR, "data", "raw")   # 数据文件 (characters_raw.json 用于职业映射)


# =============================================================================
#  1. 全局背景参数 (Global Background Config)
# =============================================================================
# 最终输出画布尺寸
CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 576

# POT 纹理裁剪常量：源素材 1024x1024，有效区域为中间 1024x576（上下各 224px 黑边）
SRC_POT_SIZE = 1024
SRC_EFFECTIVE_HEIGHT = 576

# 是否在底层铺纯黑不透明实底
BG_BLACK_BASE = False

# 背景整体亮度系数（1.0 = 原样；>1.0 增亮，<1.0 压暗）
BG_BRIGHTNESS = 1.0


# =============================================================================
#  2. 单张卡牌尺寸与布局 (Card Config)
# =============================================================================
# 十连中每张卡片统一缩放到此尺寸
CARD_WIDTH = 112
CARD_HEIGHT = 305
CARD_GAP = -16                       # 卡片间距（也是分隔条宽度）

# 卡片在画布中的垂直位置（居中 = (画布高 - 卡高) / 2）
CARD_CENTER_Y = True               # 若 True，卡片垂直居中；若 False，用 CARD_START_Y
CARD_START_Y = (CANVAS_HEIGHT - CARD_HEIGHT) // 2   # 垂直起始 Y（CARD_CENTER_Y=False 时生效）


# =============================================================================
#  3. 角色立绘 (Avatar / Portrait Config)
# =============================================================================
# 立绘宽度占卡背宽度的比例
PORTRAIT_SCALE = 1.35

# 立绘放置：底部留白给职业图标
PORTRAIT_BOTTOM_MARGIN = 0

# 立绘相对卡片的偏移量（调整半身像在卡片内的相对位置）
AVATAR_OFFSET_X = 6            # 立绘水平偏移(像素)：正=右移, 负=左移, 0=居中
AVATAR_OFFSET_Y = -18          # 立绘垂直偏移(像素)：正=下移, 负=上移, 0=底部对齐

# 立绘裁剪设置：控制半身像如何被截断在卡片内
AVATAR_CROP_TO_CARD = True        # True: 半身像强制裁剪到卡片边界内
                                  # False: 半身像允许溢出卡片(顶部/左右可超出,不被裁剪)
# 立绘裁剪边距(像素)。仅在 AVATAR_CROP_TO_CARD=True 时生效：
#   正数 = 额外多裁剪掉多少(向内收缩裁剪范围)
#   负数 = 允许立绘超出卡片边界多少(向外扩展,立绘溢出)
AVATAR_CROP_TOP = 0              # 顶部裁剪边距(正=多裁, 负=允许溢出)
AVATAR_CROP_BOTTOM = 0           # 底部裁剪边距
AVATAR_CROP_LEFT = 9             # 左侧裁剪边距
AVATAR_CROP_RIGHT = 9            # 右侧裁剪边距


# =============================================================================
#  4. 职业图标 (Profession Icon Config)
# =============================================================================
PROFESSION_ICON_SIZE = 82          # 职业图标边长(像素)
PROFESSION_ICON_BOTTOM = -32       # 职业图标底部距卡牌底部的距离(像素)
                                   #   负数=溢出卡片底部(需配合 OVERFLOW=True)
PROFESSION_ICON_CENTER_X = True    # 职业图标水平居中(True)；False 时用 PROFESSION_ICON_X
PROFESSION_ICON_X = 0              # 职业图标水平偏移(像素,相对卡片左边距；CENTER_X=False时用)
PROFESSION_ICON_OVERFLOW = True    # 职业图标是否为独立层显示(True):
                                   #   作为独立层画到画布上,可溢出卡片底部,不被卡片裁剪。


# =============================================================================
#  5. 星级标 (Star Strip Config)
# =============================================================================
STAR_STRIP_TOP = -10                 # 星级标距卡牌顶部的距离(像素,相对卡片顶部,
                                     #   负数=上移到卡片框外,需配合 STAR_STRIP_OVERFLOW)
STAR_STAR_SIZE = 15                # 单颗星的宽度(像素)
STAR_STRIP_STAR_GAP = 2            # 星与星之间的额外间距(像素)
STAR_STRIP_CENTER = True           # 星级标整体水平居中(True)或左对齐(False)
STAR_STRIP_OVERFLOW = True         # 星级标是否为独立层显示在卡片上方(True):
                                   #   False: 画在卡片内部(被卡片框住)。


# =============================================================================
#  6. 扩展特效参数（默认禁用，改动后才影响输出）
# =============================================================================
CARD_SHEAR_ANGLE = 0.0            # 整排卡牌的切变/倾斜角度（度）。0 = 不倾斜
TEXTURE_ROTATE_ANGLE = 0.0        # 网点纹理 (dianzhen) 的旋转角度（度）。0 = 不旋转
TEXTURE_OPACITY = 1.0             # 纹理/光效叠加的不透明度（0.0~1.0）
TEXTURE_BLEND_MODE = "NORMAL"     # 纹理/光效混合模式: "NORMAL"/"SCREEN"/"MULTIPLY"/"OVERLAY"

# 光效布局（高自由度）：为每张光效贴图独立控制【定位 + 拉伸 + 透明度 + 混合】
# 结构: { 星级: { 光效键: {布局字段} } }
LIGHT_LAYOUT = {
    4: {
        "star_4": {                       # 4★ 光柱
            "pos": (-1, 0), "anchor": "center",
            "size": (400, 600), "scale": 1,
            "opacity": 0.7, "blend_mode": "NORMAL",
        },
        "star_light": {                   # 4★ 光柱上方的星点光效 (128x128)
            "pos": (0, -130), "anchor": "center",   # 中心上移约 130px，落于 4★ 光柱上方
            "size": None, "scale": 2,             # 相对卡片宽缩放
            "opacity": 1, "blend_mode": "SCREEN", # 滤色让星光更亮
            "clip_to_ref": False,                  # 超出卡片宽度的部分自动截断
        },
    },
    6: {
        "star_6_glow": {                  # 6★ 光晕1 (底层)
            "pos": (30, -160), "anchor": "center",
            "size": (50, 50), "scale": 1.5,
            "opacity": 1.0, "blend_mode": "NORMAL",
            "angle": 20,                   # 旋转角度(度), 0=不旋转
        },
        "star_6_glow2": {                 # 6★ 光晕2 (另一位置, 复用同素材)
            "pos": (-40, 160), "anchor": "center",   # 与 glow1 分离的位置
            "size": (30, 30), "scale": 1.5,
            "opacity": 1.0, "blend_mode": "NORMAL",
            "angle": 0,                  # 旋转角度(度)
        },
        "star_6_halo": {                  # 6★ 光环
            "pos": (0, 0), "anchor": "center",
            "size": None, "scale": 1.3,
            "opacity": 1.0, "blend_mode": "NORMAL",
        },
        "star_6_beam": {                  # 6★ 光柱
            "pos": (20, 0), "anchor": "center",
            "size": (400, 545), "scale": 1,
            "opacity": 1.0, "blend_mode": "NORMAL",
            # 无标记=画布下层(垫在卡片背后): 可溢出卡片(不被框住),
            # 且位于半身像/dianzhen 之下(它们画在卡片内)
        },
        "star_6_dots_back": {             # 6★ 底层点阵 (不被卡片框住,垫在卡片背后)
            "pos": (0, 0), "anchor": "center",
            "size": (180, 460), "scale": 1,
            "opacity": 0.6, "blend_mode": "NORMAL",
            "angle": 170,                  # 旋转角度(度)
            "tint": (223, 145, 40),       # 点阵颜色(可单独设置, None=用 DOTS_COLOR)
            # 裁剪到光柱矩形范围内(框在光柱内):
            "clip_box": {"w": 80, "h": 500, "ox": 0, "oy": -150},
            # 无 on_card: 画布下层, 不被卡片框住(但被光柱框住)
        },
        "star_6_dots": {                  # 6★ 点阵 (网点纹理, 被卡片框住)
            "pos": (0, -80), "anchor": "center",
            "size": (280, 440), "scale": 1,
            "opacity": 1.0, "blend_mode": "NORMAL",
            "angle": -20,                  # 旋转角度(度)
            "tint": (51, 42, 46),       # 点阵颜色(可单独设置, None=用 DOTS_COLOR)
            "on_card": True,              # 卡片内层: 绘制在卡背之上、半身像之下
            "clip_to_ref": True,          # 裁剪到卡片边界内(被卡片框住,不溢出)
            "clip_box": {"w": 123, "h": 400, "ox": 0, "oy": 0},
        },
        "star_6_top_glow": {              # 6★ 光柱顶部亮渐变光晕(程序生成)
            "pos": (2, -220), "anchor": "center",   # 与光柱对齐(ox=20, 偏上200)
            "size": (100, 200), "scale": 1,          # 与 STAR_6_TOP_GLOW.size 一致
            "opacity": 1.0, "blend_mode": "SCREEN",   # 滤色让亮色更亮
            "clip_box": {"w": 400, "h": 565, "ox": 20, "oy": 0},  # 框在光柱内
            # 无 on_card: 画布下层, 溢出卡片, 但被光柱框住
        },
        "star_6_sparkles": {             # 6★ 光柱内随机小亮条(程序生成, 与5★同机制)
            "pos": (20, 0), "anchor": "center",
            "size": (500, 565), "scale": 1,
            "opacity": 1.0, "blend_mode": "SCREEN",   # 滤色叠加
            "clip_box": {"w": 400, "h": 565, "ox": 20, "oy": 0},  # 框在6★光柱内
            # 无 on_card: 画布下层, 但被光柱框住
        },
    },
    5: {
        "star_5": {                       # 5★ 光柱
            "pos": (-1, 0), "anchor": "center",
            "size": (600, 600), "scale": 1,
            "opacity": 1.0, "blend_mode": "NORMAL",
        },
        "star_5_sparkles": {             # 5★ 光柱内随机小亮条(程序生成)
            "pos": (0, 0), "anchor": "center",
            # size 与 clip_box 的 w/h 一致, 避免渲染时被缩放破坏亮条分布
            "size": (400, 565), "scale": 1,
            "opacity": 1.0, "blend_mode": "SCREEN",   # 滤色叠加
            "clip_box": {"w": 400, "h": 565, "ox": 0, "oy": 0},  # 框在5★光柱内
            # 无 on_card: 画布下层, 但被光柱框住
        },
        "star_5_top_glow": {             # 5★ 光柱顶部亮渐变光晕(程序生成)
            "pos": (0, -220), "anchor": "center",   # 与光柱对齐, 偏上
            "size": (400, 180), "scale": 1,
            "opacity": 1.0, "blend_mode": "SCREEN",   # 滤色让亮色更亮
            "clip_box": {"w": 400, "h": 565, "ox": 0, "oy": 0},  # 框在光柱内
            # 无 on_card: 画布下层, 溢出卡片, 但被光柱框住
        },
    },
}


# 6★ 卡背渐变色参数：给 6★ 背景卡片叠加一层渐变色调
CARD_GRADIENT = {
    "enabled": True,                 # 是否启用 6★ 卡背渐变
    "color_top": (237, 90, 16),     # 顶部渐变颜色 (R, G, B)
    "color_bottom": (203, 201, 73),    # 底部渐变颜色 (R, G, B)
    "opacity": 1,                  # 渐变透明度(程度, 0~1): 越大渐变越明显
    "direction": "vertical",         # 渐变方向: "vertical"(上下) / "radial"(径向)
    "blend_mode": "NORMAL",          # 渐变叠加方式: "NORMAL" / "SCREEN" / "MULTIPLY" / "OVERLAY"
    "pos": (0, -200),                # 起始偏移 (x, y)
    "size": (124, 378),              # 范围 (w, h): 0/None=全卡片宽/高
}


# 星点光效 (star_light) 的着色参数：把白色光球渲染成"中心白、向外扩散成紫"
STAR_LIGHT_COLOR = {
    "purple": (140, 60, 230),         # 浓郁紫色 (R, G, B)，整体氛围主色
    "white_radius": 0.01,             # 白色高光"感知大小"
    "center_power": 1,              # 衰减锐度
    # 外层光晕(halo)：紫色氛围光,从中心向外扩散充满
    "halo_enabled": True,
    "halo_scale": 1.5,                # 光晕衰减指数
    "halo_opacity": 0.85,             # 光晕最大透明度
    "halo_softness": 1.0,             # 光晕衰减柔和度
}


# dianzhen 网点纹理 (dots) 的着色参数
DOTS_COLOR = (140, 60, 230)          # dianzhen 网点主色 (R, G, B)


# 6★ 光柱顶部亮渐变光晕 (程序生成)
STAR_6_TOP_GLOW = {
    "size": (700, 500),             # 渐变图尺寸 (w, h)
    "color_bright": (255, 251, 102), # 底部亮色 (R, G, B)
    "color_dark": (83, 51, 11),    # 顶部暗色 (R, G, B)
    "opacity": 1,                # 透明度(程度)
}


# 5★ 光柱顶部亮渐变光晕 (程序生成, 与 6★ 同机制)
STAR_5_TOP_GLOW = {
    "size": (300, 180),             # 渐变图尺寸 (w, h)
    "color_bright": (255, 200, 90), # 底部亮色 (R, G, B)
    "color_dark": (100, 40, 10),    # 顶部暗色 (R, G, B)
    "opacity": 0.7,                # 透明度(程度)
}


# 5★ 光柱内随机小亮条 (程序生成, 第二张参考图效果)
SPARKLES_CONFIG = {
    "count": 12,                   # 亮条数量 (调整数量)
    "seed": 42,                    # 随机种子(固定数字, 可复现; 改此值换一版分布)
    "bar_width": (3, 6),           # 亮条宽度范围 (min, max) 像素
    "bar_height": (8, 20),         # 亮条高度范围 (min, max) 像素
    "color": (255, 255, 255),      # 亮条颜色 (默认白色, 可调)
    "alpha": (150, 230),           # 亮条 alpha 范围 (min, max), 0~255
    # 不生成区域(可选): 亮条中心落在这些矩形内的不会生成。
    "exclude_zone": [{"x": 100, "y": 200, "w": 200, "h": 400}],
}


# 5★ 光柱内随机小亮条 (保留别名, 与 6★ 共用 SPARKLES_CONFIG 生成参数)
STAR_5_SPARKLES = SPARKLES_CONFIG


# 光柱范围可视化调试参数
DEBUG_SHOW_BOUNDS = {
    "enabled": False,            # True 显示光柱/光效的 clip_box 边框
    "color": (255, 0, 255),      # 边框颜色 (品红)
    "width": 1,                  # 边框线宽(像素)
}


# =============================================================================
#  素材文件名映射 (Material File Mapping)
#     把逻辑用途映射到插件实际目录下的文件名。
# =============================================================================
# 背景：优先加载已预合成的 16:9 背景图
BACKGROUND_FILE = "gacha_beijing_composed.png"
# 若合成图缺失时的回退前景素材
BACKGROUND_FALLBACK = "gacha_beijing_1.png"

SEPARATOR_FILE = "sprite_avg_cutscene.png"      # 卡牌间的分隔条素材

# 卡背底框：游戏星级 → 文件名
CARD_BACK_FILES = {
    3: "back_low_1_3.png",
    4: "back_four.png",
    5: "back_five.png",
    6: "back_five.png",             # 6★ 复用 5★ 底，靠光效区分
}

# 星级标：游戏星级 → 文件名
STAR_STRIP_FILES = {
    1: "star_1.png", 2: "star_2.png", 3: "star_3.png",
    4: "star_4.png", 5: "star_5.png", 6: "star_6.png",
}

# 光效贴图：逻辑键 → 文件名
LIGHT_FILES = {
    "star_4": "sixing_01.png",               # 4★ 光柱
    "star_5": "wuxingguang_01.png",          # 5★ 光柱
    "star_6_glow": "guangxiao_03.png",       # 6★ 光晕1 (底层)
    "star_6_glow2": "guangxiao_03.png",      # 6★ 光晕2 (不同位置,复用同素材)
    "star_6_halo": "trail_06.png",           # 6★ 光环
    "star_6_beam": "liuxingguangyun_01.png", # 6★ 光柱
    "star_6_dots": "dianzhen_01.png",        # 6★ 点阵 (网点纹理, 被卡片框住)
    "star_6_dots_back": "dianzhen_01.png",   # 6★ 底层点阵 (不被卡片框住,垫底)
    "star_light": "star_light.png",          # 光柱上方的星点光效 (128x128)
}
