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

# ── 运行时数据目录 ──────────────────────────────────────────────────────────
# AstrBot 规范：插件运行期间产生的数据（下载缓存、抓取数据、字体、数据库等）
# 必须存放在框架分配的【插件专属数据目录】 data/plugin_data/<插件名>/，
# 不得写入 AstrBot 的 data/ 根目录，也不得写入插件安装目录
# （插件目录属于只读资源区，随插件更新会被整体覆盖）。
#
# 取值优先级：
#   1. 插件入口 main.py 调用框架公开 API StarTools.get_data_dir() 后经 set_data_dir() 注入
#   2. 环境变量 ARKGACHA_DATA_DIR —— 插件以子进程方式调用 tools/ 下的数据脚本时注入，
#      保证子脚本写入的位置与插件读取的位置一致
#   3. 插件目录下的 data/ —— 仅在脱离 AstrBot 手动运行 tools/ 脚本时使用（本地开发）
DATA_DIR = os.environ.get("ARKGACHA_DATA_DIR") or os.path.join(PLUGIN_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")                                # 动态下载/生成缓存总目录

# 各资源子目录（与 Generator_test config.py 的目录语义一一对应）
BG_DIR = MATERIAL_DIR              # 背景底图 / 分隔条 (16:9 / 1024x1024)
CARD_DIR = STATE_DIR               # 卡牌底框 (back_low_* / back_four / back_five)
TEXTURE_DIR = STATE_DIR            # 网点 / 纹理 / 光效贴图 (dianzhen / guangxiao 等)
STAR_DIR = STATE_DIR               # 星级标 (star_1 ~ star_6)
PROF_DIR = os.path.join(CACHE_DIR, "professions")   # 职业图标 (动态下载缓存)
PROFESSION_LABELED_DIR = os.path.join(CACHE_DIR, "professions_labeled")  # 带文字职业图标 (单抽用)
PORTRAIT_DIR = os.path.join(CACHE_DIR, "portraits") # 角色半身像 / 立绘 (动态下载缓存)
ELITE1_ART_DIR = os.path.join(CACHE_DIR, "elite1_art")  # 单抽用干员精一立绘 (动态下载缓存, 降质存储)
RAW_DIR = os.path.join(DATA_DIR, "raw")     # 数据文件 (characters_raw.json 用于职业映射)
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")   # 清洗后的卡池/规则数据

# 字体目录。字体【不随插件包分发】，由 font_manager 在首次需要时从官方源下载到
# FONT_DIR（位于插件专属数据目录下），以减少插件包体积。
# 若使用者想跳过下载，也可手动把字体放到 FALLBACK_FONT_DIR（随插件分发的只读位置）。
FONT_DIR = os.path.join(DATA_DIR, "fonts")
FALLBACK_FONT_DIR = os.path.join(PLUGIN_DIR, "assets", "fonts")

def set_data_dir(path: str) -> None:
    """
    注入 AstrBot 分配的插件专属数据目录（data/plugin_data/<插件名>/）。

    由插件入口 main.py 在初始化时调用，调用来源必须是框架公开 API：
        from astrbot.api.star import StarTools
        set_data_dir(StarTools.get_data_dir(PLUGIN_NAME))

    所有运行时数据（缓存 / 抓取数据 / 字体 / 数据库）都会落到该目录下，
    既不会污染 AstrBot 的 data/ 根目录，也不会写入会被更新覆盖的插件目录。
    """
    global DATA_DIR, CACHE_DIR, RAW_DIR, PROCESSED_DIR, FONT_DIR
    # 下面这 4 个缓存子目录常量是在【模块导入时】用当时的 CACHE_DIR 绑定死的，
    # 必须在这里一并重算！否则它们会停留在默认的 <插件目录>/data/cache 下，
    # 而写入方（image_renderer 用的是 cfg.CACHE_DIR，属性访问拿到新值）走的是
    # 插件专属数据目录 —— 造成"写的目录"和"读的目录"永久错位：
    # 半身像 / 职业图标 / 带文字职业图标 / 精一立绘 会全部读不到。
    global PROF_DIR, PROFESSION_LABELED_DIR, PORTRAIT_DIR, ELITE1_ART_DIR
    DATA_DIR = str(path)
    CACHE_DIR = os.path.join(DATA_DIR, "cache")
    RAW_DIR = os.path.join(DATA_DIR, "raw")
    PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
    FONT_DIR = os.path.join(DATA_DIR, "fonts")
    PROF_DIR = os.path.join(CACHE_DIR, "professions")
    PROFESSION_LABELED_DIR = os.path.join(CACHE_DIR, "professions_labeled")
    PORTRAIT_DIR = os.path.join(CACHE_DIR, "portraits")
    ELITE1_ART_DIR = os.path.join(CACHE_DIR, "elite1_art")


def ensure_data_dirs() -> None:
    """
    确保运行时数据子目录存在。

    数据拉取脚本（tools/ 下）会直接向 raw/、processed/ 写文件，
    目录不存在时会因 [Errno 2] 写入失败。插件入口与各数据脚本在写入前
    都应先调用本函数。
    """
    for d in (DATA_DIR, CACHE_DIR, RAW_DIR, PROCESSED_DIR, FONT_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


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
#  7. 单抽图参数（插件扩展，Generator_test 无此功能）
#     单抽与十连共用同一套图层顺序与光效布局，只是把单张卡居中放大；
#     合成时按下面的比例算出统一缩放倍率 zoom，光效尺寸/偏移/裁剪框同步放大，
#     保证单抽卡面构图与十连中的同一张卡完全一致。
# =============================================================================
# 放大后的卡片高度（宽度按比例）占画布高度的比例：0.92 = 卡片高度约占画布 92%
SINGLE_PULL_CARD_FILL = 0.92


# =============================================================================
#  8. 单抽·干员立绘缓存参数（插件扩展）
#     立绘统一取精英1立绘(立绘_<干员名>_1.png)，使各星级风格一致；
#     极少数缺精一立绘的干员才兜底精英2立绘(立绘_<干员名>_2.png)。
#     立绘的构图/位置/大小已迁到第 9 节 SP3_ELEMENTS["portrait"]，此处只管缓存。
# =============================================================================
# 立绘缓存画质档位。由 AstrBot 插件配置页的 portrait_cache_quality 选择，
# 未配置 / 非法值时回退到 DEFAULT_PORTRAIT_QUALITY。
#   max_height: 0 = 不降采样（原画质）
#   format    : "PNG"（无损）/ "WEBP"（有损，体积小）
#   quality   : 仅 WEBP 生效，取 1~100
# 每个档位在 elite1_art/ 下独占一个子目录，因此切换档位会自动重新缓存，
# 不会与其它档位的缓存互相覆盖（旧档位目录可手动删除以释放空间）。
PORTRAIT_QUALITY_PRESETS = {
    "original": {"max_height": 0,    "format": "PNG",  "quality": 100},
    "high":     {"max_height": 1080, "format": "WEBP", "quality": 95},
    "medium":   {"max_height": 810,  "format": "WEBP", "quality": 88},
    "low":      {"max_height": 640,  "format": "WEBP", "quality": 78},
}
DEFAULT_PORTRAIT_QUALITY = "original"


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


# =============================================================================
#  9. 单抽结果图 · 元素表（插件扩展）
#     本配置块是单抽合成器的唯一调参入口：改这里的数值即可调整构图，无需改代码。
#
#  通用字段（所有元素）：
#    pos       相对【画布中心】的偏移 (x, y)；(0, 0) = 正中心
#              目前全部默认堆在中心，请按需调开。
#    size      等比缩放百分比：100 = 素材原始尺寸，50 = 缩小一半，200 = 放大一倍；
#              None 等价于 100；也可传 (w_pct, h_pct) 分别控制宽高（非等比，少用）
#    opacity   不透明度 0.0 ~ 1.0
#    blend     混合模式：NORMAL / SCREEN / MULTIPLY / OVERLAY
#    layer     层级：数值【越小越靠上层】（后绘制，会遮挡下层）
#              注意这与常见直觉相反，调整时请留意。
#    enabled   是否绘制该元素
#
#  文字元素额外字段：
#    text              取值来源："cn"（中文名）/ "en"（英文名）
#    font_size         字号（像素）
#    font              指定字体文件名（留空 = 按语言自动选：
#                      中文→思源黑体 Heavy，英文→Oxanium SemiBold）
#    weight            可变字体字重（Oxanium 用 600；思源黑体为静态 Heavy，忽略）
#    fill              填充色
#    stroke_fill       描边色（当前默认灰色）
#    stroke_width      描边宽度，单位【像素】（纯外描边，不外侵字芯）；
#                      0 = 不描边。填 1 即为 1px 描边，与实际厚度一致
#    uppercase         True = 文字转全大写（英文名常用）
#    letter_spacing    字距比例（相对字号）
#    align             相对 pos 的水平对齐：left / center / right
#    color_mode        True = 忽略描边，直接以 fill 绘制彩色文字
#
#  星级元素（stars）额外字段：
#    size              单颗星的等比缩放百分比（同其它元素，100 = 素材原始尺寸）
#    gap               相邻两颗星之间的像素间距（绝对像素，非百分比）
#    align             整组相对 pos 的水平对齐
#    count_from_rarity True = 数量取干员星级；False = 使用 fixed_count
#    fixed_count       count_from_rarity 为 False 时的固定数量
# =============================================================================
SP3_CANVAS = (CANVAS_WIDTH, CANVAS_HEIGHT)

# 单抽专用背景：十连背景的局部放大版（与十连并非同一张图，已缩放到 1024x576）。
# 该文件缺失时，可把下面 background 元素的 file 改回 BACKGROUND_FILE 兜底。
SP3_BACKGROUND_FILE = "gacha_beijing_composed_single.png"

SP3_ELEMENTS = {
    # ──────────────────────── 背景（单抽专用）────────────────────────
    "background": {
        "file": SP3_BACKGROUND_FILE, "layer": 100, "pos": (0, 0), "size": 100,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────────────────── 干员精一立绘 ────────────────────────
    "portrait": {
        "layer": 40, "pos": (130, 85),
        "fill": 1.0,           # 立绘高度占画布高度的比例
        "size_percent": 120,   # 再乘一个百分比：100 = 不缩放，>100 = 放大
        "enabled": True,
    },

    # ──────────────────────── 阵营 logo ────────────────────────
    "camp_logo": {
        "layer": 41, "pos": (-112, -50), "size": 66,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────────────────── 带文字职业图标 ────────────────────────
    "profession": {
        "layer": 24, "pos": (-70, 143), "size": 83,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────── 装饰素材（固定画上，不随星级变化，也非星级用途）────────────
    # ↓ 以下 4 个装饰元素均启用【随机副本】：
    #   random_count > 0 时忽略固定 pos，在 random_area 范围内随机生成 N 个（允许重叠）。
    #   random_area 坐标同样相对画布中心：x 取 ±512 = 画布全宽；y 取 >-250 = 画面中上部起。
    "deco_star04": {
        "file": "star_04.png", "layer": 51, "pos": (250, 250), "size": 100,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
        "random_count": 3,
        "random_area": {"x": (-512, 512), "y": (-100, 280)},
        # 每个副本各自的【随机尺寸范围】（百分比，100 = 素材原始大小）
        "random_size": (60, 80),
        # 以下两项仅对【翻转后】的副本生效（需先配 rotate_chance）：
        "rotated_offset": (0, 0),         # 相对原随机位置的额外偏移（调 y 就是调高度）
        "rotated_tint": (235, 150, 105),  # 染成暖橙色（None = 不染色）
        # 附属拖尾：程序绘制的柔和光柱，每个实例 50% 概率出现
        "trail": {
            "type": "beam",             # "beam" = 程序绘制光柱 / "image" = 用 file 素材
            "chance": 0.3,              # 出现概率
            "layer_offset": 0.5,        # 层级 = 所属 star 层 + 该值。
                                        # 【必须用小数】：+0.5 = 紧贴自身 star 的下一层
                                        # （负数会让光柱盖住 star；整数会撞到相邻 star 的层）
            "size_ratio": 1.0,          # 基准尺寸 = star 尺寸 × 该比例
            # 尺寸二选一：填 *_px 用【绝对像素】；不填则用倍率 × star 尺寸。
            # 倍率是【相对 star 的倍数】：0.35 ≈ 45px；填 20 = 2560px（画布才 1024），
            # 柱形会被截平成一整片平光，所以想精确控制请直接用 beam_width_px。
            "beam_width": 0.3,         # 光柱宽 = star 宽 × 该值（0.1~1.5 较合理）
            "beam_height": 1.8,         # 光柱高 = star 高 × 该值
            # 平顶比例：中心这一段保持【全亮】，只有外侧羽化。
            # 想要参考图那种"粗条状光柱"就调大它 —— 光靠 beam_width 加宽
            # 只会把半透明的雾气摊得更开，看着仍然像一条细线。
            "flat_ratio": 0.7,          # 0 = 纯锥形（细） / 0.5 = 中心一半是实的（粗条）
            "softness_x": 1.2,          # 横向边缘衰减：有平顶后只影响外侧（越大越柔）
            "softness_y": 1.0,          # 纵向衰减
            "color": (255, 255, 255),   # 光柱颜色（未翻转的 star 用这个）
            "rotated_color": None,      # 所属 star 翻转时的光柱颜色；None = 跟随 rotated_tint
            "opacity": 0.8,             # 整体淡度（要"淡"就调小）
            "blend": "SCREEN",          # 光柱推荐用 SCREEN 叠加
            "follow_rotate": True,      # 是否跟随所属 star 一起翻转
            "offset": (0, 0),           # 相对所属 star 的偏移
        },
    },
    "deco_star24": {
        "file": "star_24.png", "layer": 72, "pos": (200, -200), "size": 100,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
        "random_count": 3,
        "random_area": {"x": (-512, 512), "y": (-100, 280)},
        "random_size": (60, 80),
        "rotated_offset": (0, 0), "rotated_tint": (235, 150, 105),
        "trail": {
            "type": "beam", "chance": 0.3, "layer_offset": 0.5,
            "size_ratio": 1.0, "beam_width": 0.2, "beam_height": 1.8,
            "flat_ratio": 0.7,
            "softness_x": 1.2, "softness_y": 1.0, "color": (255, 255, 255),
            "rotated_color": None,      # 翻转时改用的光柱颜色；None = 跟随 rotated_tint
            "opacity": 0.8, "blend": "SCREEN", "follow_rotate": True,
            "offset": (0, 0),
        },
    },
    "deco_star25": {
        "file": "star_25.png", "layer": 53, "pos": (-200, 200), "size": 100,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
        "random_count": 3,
        "random_area": {"x": (-512, 512), "y": (-100, 280)},
        "random_size": (60, 80),
        "rotated_offset": (0, 0), "rotated_tint": (235, 150, 105),
        "trail": {
            "type": "beam", "chance": 0.3, "layer_offset": 0.5,
            "size_ratio": 1.0, "beam_width": 0.2, "beam_height": 1.8,
            "flat_ratio": 0.7,
            "softness_x": 1.2, "softness_y": 1.0, "color": (255, 255, 255),
            "rotated_color": None,      # 翻转时改用的光柱颜色；None = 跟随 rotated_tint
            "opacity": 0.8, "blend": "SCREEN", "follow_rotate": True,
            "offset": (0, 0),
        },
    },
    "deco_star26": {
        "file": "star_26.png", "layer": 54, "pos": (-200, -200), "size": 100,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
        "random_count": 8,
        "random_area": {"x": (-512, 512), "y": (-100, 280)},
        "random_size": (60, 80),
        # 90% 概率翻转 180°，翻转后的实例改用 rotated_layer
        "rotate_chance": 0.7,
        "rotated_layer": 61,
        "rotated_offset": (0, -20),         # 翻转后的实例额外偏移（调 y 即调高度）
        "rotated_tint": (235, 150, 105),  # 翻转后染成暖橙色
        "trail": {
            "type": "beam", "chance": 0.3, "layer_offset": 0.5,
            "size_ratio": 1.0, "beam_width": 0.3, "beam_height": 1.8,
            "flat_ratio": 0.7,
            "softness_x": 1.2, "softness_y": 1.0, "color": (255, 255, 255),
            "rotated_color": None,      # 翻转时改用的光柱颜色；None = 跟随 rotated_tint
            "opacity": 0.8, "blend": "SCREEN", "follow_rotate": True,
            "offset": (0, 0),
        },
    },
    # 放射状星形装饰底纹（512x512）。默认层值比名字大 => 垫在名字下方，
    # 若你想让它盖住名字，把 layer 调到比 name_cn(10)/name_en(11) 更小即可。
    "deco_beijing05": {
        "file": "beijing_05.png", "layer": 90, "pos": (66, -20), "size": 155,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────── SKIP 跳过按钮（结算图右下角常见）────────────
    "btn_skip": {
        "file": "btn_skip.png", "layer": 1, "pos": (450, -240), "size": 80,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
        # 界面元素：在打光【之后】绘制，保证不被画面暗角压暗（保持纯亮）
        "above_vignette": True,
        # 程序生成的底板（素材 btn_skip.png 只有白色文字+三角，没有底）
        "backdrop": {
            "enabled": True,
            "color": (28, 30, 34, 210),   # 灰黑底（alpha 控制虚实）
            "size": (75, 55),            # 底板宽高（像素）
            "radius": 0,                  # 圆角半径，0 = 直角
            "offset": (0, 0),             # 相对按钮中心的偏移
        },
    },

    # ──────────── 星级五角星（数量 = 干员星级）────────────
    "stars": {
        "file": "wujiaoxing_01.png", "layer": 19, "pos": (-147, 72),
        "size": 47,                # 单颗等比缩放百分比（100 = 素材原始 256x256）
        "gap": -51,                   # 相邻两颗的像素间距
        "align": "left",            # 整组水平对齐：left / center / right
        "count_from_rarity": True,  # True = 数量取星级
        "fixed_count": 6,           # count_from_rarity=False 时使用
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────── NEW 标记（预留：首次抽到才显示）────────────
    # 注意：enabled 必须保持 True，否则元素不会进入绘制管线，
    #       is_new=True 也无法显示。真正是否绘制由 render_single_pull(is_new=...)
    #       决定；默认 is_new=False，即不显示。
    "new_tag": {
        "file": "sprite_new.png", "layer": 23, "pos": (-40, 185), "size": 80,
        "opacity": 1.0, "blend": "NORMAL", "enabled": True,
    },

    # ──────────────────────── 干员中文名 ────────────────────────
    "name_cn": {
        "layer": 21, "pos": (8, 143), "opacity": 1.0, "blend": "NORMAL",
        "enabled": True,
        "text": "cn", "font_size": 59, "font": "HarmonyOS_Sans_SC_Bold.ttf",
        "weight": 900,
        # 描边用【半透明黑】：亮背景上叠出灰色轮廓（实测≈165，与原版一致），
        # 暗背景上几乎不可见，实现自适应分离。alpha 越大描边越明显。
        "fill": (255, 255, 255, 255), "stroke_fill": (0, 0, 0, 80),
        "stroke_width": 1, "letter_spacing": 0.0,
        "align": "left", "color_mode": False,
    },

    # ──────────────────────── 干员英文名 ────────────────────────
    "name_en": {
        "layer": 22, "pos": (8, 186), "opacity": 1.0, "blend": "NORMAL",
        "enabled": True,
        "text": "en", "font_size": 25, "font": "HarmonyOS_Sans_SC_Bold.ttf",
        "weight": 600,
        # 描边同为半透明黑（与原版一致）：亮背景显灰、暗背景近乎消失
        "fill": (255, 255, 255, 255), "stroke_fill": (0, 0, 0, 80),
        "stroke_width": 1, "letter_spacing": 0.02, "uppercase": True,
        "align": "left", "color_mode": False,
    },
}

# -----------------------------------------------------------------------------
#  单抽·打光（椭圆暗角）
#    效果：画面四周偏暗、中心展示人物等主题的区域保持正常亮度。
#    椭圆内部不压暗，向外按羽化曲线渐变到最暗。
# -----------------------------------------------------------------------------
SP3_VIGNETTE = {
    "enabled": True,
    "layer": 11,              # 置于最上层（比所有元素都小）
    "center": (0, 0),        # 椭圆中心相对画布中心的偏移
    "size": (1100, 600),      # 椭圆直径 (宽, 高)
    "feather": 0.35,         # 羽化程度：0 = 硬边，越大过渡越柔和
    "darkness": 0.7,        # 最暗处的不透明度（0 ~ 1，越大四周越黑）
    "color": (0, 0, 0),      # 暗角颜色
    "invert": False,         # True = 反转（中心变暗、四周亮）
    "power": 1.1            # 渐变曲线指数：>1 更集中，<1 更平缓
}

# -----------------------------------------------------------------------------
#  单抽·底部渐变遮罩（三段式，自下而上）
#    [ solid_height ] 纯色段：完全不透明（alpha = max_alpha）
#    [ fade_height  ] 渐变段：alpha 由 max_alpha 渐隐到 0
#    [     其余     ] 全透明
#    总覆盖高度 = solid_height + fade_height，两段各自独立可控。
#    是独立配置块，通过 layer 参与统一排序，语义与元素表一致。
# -----------------------------------------------------------------------------
SP3_BOTTOM_FADE = {
    "enabled": True,
    "layer": 12,              # 越小越靠上层；2 = 仅低于打光(1)，盖在其余元素之上
    "color": (0, 0, 0),      # 渐变色
    "max_alpha": 255,        # 纯色段的不透明度（255 = 完全不透明纯黑）
    "solid_height": 40,      # ① 底部【纯色】段高度（像素）：此段不渐变，恒为纯黑
    "fade_height": 60,      # ② 纯色段之上的【渐变】段高度（像素）：alpha → 0
    "power": 1.0,            # 渐变速率：1.0 = 线性；>1 过渡更靠下部，<1 更平缓
    "pos": (0, 0),           # 偏移 (x, y)；y 为负则整体上移
}
