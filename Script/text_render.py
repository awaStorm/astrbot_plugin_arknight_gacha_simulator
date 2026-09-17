# -*- coding: utf-8 -*-
"""
text_render.py - 中英文混排文字渲染（白色填充 + 黑色外描边）

字体分工：
  · 汉字 / 全角符号 / 常见符号 -> 思源黑体 Heavy（SourceHanSansCN-Heavy.otf）
  · 英文 / 数字 / 半角符号     -> Oxanium 可变字体（SemiBold = 600）

描边实现要点（关键）：
  Pillow 的 stroke_width 是【居中描边】——描边宽度的一半压在字芯内侧，
  直接用会让白字变细、小字号下甚至糊成一团。
  这里采用"两倍宽度先描边、再用填充覆盖"的做法，得到纯【外描边】：
      1) stroke_width = 2W、fill 与 stroke_fill 同为黑色 -> 轮廓向外扩 W
      2) stroke_width = 0、fill = 白色              -> 字芯盖回，字重零损失
  同时所有分段统一走"先画全部描边、再画全部填充"，
  避免相邻分段的描边压到前一段的字芯上。

中英混排：
  Pillow 不会自动做字体回退（缺字形会画方框/空白）。
  因此按字符逐段切分，同一段内用同一字体，逐段累加 x 绘制，
  并用 baseline（anchor="ls"）对齐，保证中英文字面基线一致。

所有对外函数在字体缺失/文本为空时都【不抛异常】，仅返回空结果，
由调用方决定是否跳过该文字层。
"""

import os

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
#  路径与字体候选
# ---------------------------------------------------------------------------
# 本文件位于 <插件根>/Script/ ，插件根为其上一级
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 字体查找目录（按优先级）：
#   1. data/fonts   —— font_manager 首次运行时从官方源下载并缓存（推荐）
#   2. assets/fonts —— 使用者手动放置字体的位置，可跳过自动下载
FONT_DIR = os.path.join(ROOT_DIR, "data", "fonts")
FALLBACK_FONT_DIR = os.path.join(ROOT_DIR, "assets", "fonts")
FONT_SEARCH_DIRS = (FONT_DIR, FALLBACK_FONT_DIR)

# 按顺序查找，命中第一个存在的文件。
# 未在元素配置里指定 font 时，中英文都默认走这套候选。
CJK_FONTS = [
    "HarmonyOS_Sans_SC_Bold.ttf",      # 当前使用（鸿蒙黑体 Bold）
    "SourceHanSansCN-Heavy.otf",       # 兜底
]

LATIN_FONTS = [
    "HarmonyOS_Sans_SC_Bold.ttf",      # 自带拉丁字形，中英文统一
    "SourceHanSansCN-Heavy.otf",       # 兜底
]


# ---------------------------------------------------------------------------
#  字体加载（带缓存；可变字体按字重实例化）
# ---------------------------------------------------------------------------
_font_cache = {}
_missing_warned = set()


def resolve_font_path(kind: str, font_file: str = "") -> str:
    """
    解析字体文件路径。

    font_file 非空时优先使用指定文件名（在 FONT_SEARCH_DIRS 中查找，也允许绝对路径）；
    为空时按 kind（"latin" / "cjk"）从候选列表里找。
    全部缺失返回空字符串。
    """
    if font_file:
        if os.path.isabs(font_file):
            return font_file if os.path.isfile(font_file) else ""
        for d in FONT_SEARCH_DIRS:
            p = os.path.join(d, font_file)
            if os.path.isfile(p):
                return p
        return ""
    candidates = LATIN_FONTS if kind == "latin" else CJK_FONTS
    for d in FONT_SEARCH_DIRS:
        for fn in candidates:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return p
    return ""


def get_font(kind: str, size: int, weight: int = 700, font_file: str = ""):
    """
    获取字体对象（缓存复用）。字体缺失时返回 None（不抛异常）。

    kind:      "latin" 英文字体 / "cjk" 中文字体
    size:      字号（像素）
    weight:    可变字体字重（Oxanium 用 600）；静态字体忽略该参数
    font_file: 指定字体文件名，覆盖 kind 的自动选择
    """
    size = max(1, int(size))
    key = (kind, size, weight, font_file)
    if key in _font_cache:
        return _font_cache[key]

    path = resolve_font_path(kind, font_file)
    if not path:
        if kind not in _missing_warned:
            _missing_warned.add(kind)
            print(f"[text_render] 警告: 找不到 {kind} 字体；"
                  f"已尝试 {list(FONT_SEARCH_DIRS)}")
        return None

    try:
        font = ImageFont.truetype(path, size)
    except Exception:
        return None

    # 可变字体: 设置字重轴，其余轴保持默认值；静态字体读取轴会抛异常，忽略即可
    try:
        axes = font.get_variation_axes()
    except Exception:
        axes = None
    if axes:
        try:
            vals = []
            for ax in axes:
                name = ax.get("name", b"")
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "ignore")
                if name.lower() == "weight":
                    vals.append(max(ax["minimum"], min(weight, ax["maximum"])))
                else:
                    vals.append(ax.get("default", 0))
            font.set_variation_by_axes(vals)
        except Exception:
            pass

    _font_cache[key] = font
    return font


def clear_font_cache():
    """清空字体缓存（字体文件更新后调用）"""
    _font_cache.clear()
    _missing_warned.clear()


# ---------------------------------------------------------------------------
#  字符分类与分段
# ---------------------------------------------------------------------------
def _is_cjk(ch: str) -> bool:
    """判断字符是否应由中文字体渲染（含常见符号的 fallback）"""
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF or      # CJK 统一汉字
        0x3400 <= o <= 0x4DBF or      # 扩展 A
        0xF900 <= o <= 0xFAFF or      # 兼容汉字
        0x3000 <= o <= 0x303F or      # CJK 标点符号
        0xFF01 <= o <= 0xFF60 or      # 全角 ASCII / 全角标点
        0xFFE0 <= o <= 0xFFE6 or      # 全角符号
        # 常见符号：★、♪、箭头等。latin 显示字体未必都含这些字形，
        # 交给中文字体更安全。
        0x2600 <= o <= 0x26FF or      # 杂项符号
        0x2700 <= o <= 0x27BF or      # 装饰符号
        0x2B00 <= o <= 0x2BFF         # 杂项符号与箭头
    )


def _split_runs(text: str):
    """把文本切成 [(片段, 是否中文), ...]，连续同类字符合并为一段"""
    runs = []
    buf = ""
    cur_kind = None
    for ch in text:
        kind = _is_cjk(ch)
        if cur_kind is None:
            cur_kind = kind
        if kind == cur_kind:
            buf += ch
        else:
            runs.append((buf, cur_kind))
            buf = ch
            cur_kind = kind
    if buf:
        runs.append((buf, cur_kind))
    return runs


# ---------------------------------------------------------------------------
#  测量
# ---------------------------------------------------------------------------
def measure_text(text: str, size: int, weight: int = 700,
                 letter_spacing_ratio: float = 0.0,
                 font_file: str = "") -> tuple:
    """
    测量文本尺寸，返回 (width, ascent, descent)。

    letter_spacing_ratio: 字距 = size * 该比例（只加在段内字符之间）
    font_file:            指定字体文件时，中英文都用它渲染
    字体缺失时返回 (0, 0, 0)。
    """
    if not text:
        return 0.0, 0, 0

    sp = size * letter_spacing_ratio
    total = 0.0
    ascent = descent = 0
    for run, is_cjk in _split_runs(text):
        kind = "cjk" if is_cjk else "latin"
        font = get_font(kind, size, weight, font_file)
        if font is None:
            continue
        total += font.getlength(run) + sp * max(len(run) - 1, 0)
        a, d = font.getmetrics()
        ascent = max(ascent, a)
        descent = max(descent, d)
    return total, ascent, descent


# ---------------------------------------------------------------------------
#  绘制：白色填充 + 黑色外描边
# ---------------------------------------------------------------------------
def draw_outlined_text(canvas: Image.Image, xy, text: str,
                       size: int = 32,
                       weight: int = 700,
                       fill=(255, 255, 255, 255),
                       stroke_fill=(128, 128, 128, 255),
                       stroke_width: int = 0,
                       letter_spacing_ratio: float = 0.0,
                       halign: str = "center",
                       opacity: float = 1.0,
                       font_file: str = "",
                       color_mode: bool = False):
    """
    在 canvas 上绘制"外描边 + 填充"的中英混排文字（默认白字灰边）。

    参数：
      xy                   : (x, baseline_y)。y 是【基线】位置（不是顶边）
      size                 : 字号（像素）
      weight               : 字重（Oxanium 用 600；思源黑体 Heavy 为静态，忽略）
      fill                 : 填充色
      stroke_fill          : 描边色（默认灰色）
      stroke_width         : 描边宽度，单位【像素】，纯外描边；0 = 不描边
                             （内部按 2 倍宽度绘制再覆盖填充，故填 1 就是 1px 外描边）
      letter_spacing_ratio : 字距 = size * 该比例
      halign               : "left" / "center" / "right"，相对传入的 x
      opacity              : 整体不透明度 0.0~1.0
      font_file            : 指定字体文件（中英都用它）
      color_mode           : 为 True 时忽略描边，直接以 fill 绘制彩色文字

    返回：文本实际宽度（像素）；字体缺失或文本为空时返回 0。

    实现要点：
      · 全部描边画完再画全部填充 -> 相邻中/英分段不会互相压盖
      · stroke 用 2 倍宽度 + 后覆盖填充 -> 得到纯外描边，字芯不变细
    """
    if not text:
        return 0

    sp = size * letter_spacing_ratio

    # 1) 预解析每段字体与宽度
    segs = []
    total_w = 0.0
    for run, is_cjk in _split_runs(text):
        kind = "cjk" if is_cjk else "latin"
        font = get_font(kind, size, weight, font_file)
        if font is None:
            continue
        w = font.getlength(run) + sp * max(len(run) - 1, 0)
        segs.append((run, font, w))
        total_w += w

    if not segs:
        return 0

    # 2) 水平对齐 -> 起始 x
    x0, baseline_y = xy
    if halign == "center":
        x0 -= total_w / 2.0
    elif halign == "right":
        x0 -= total_w

    # 3) 在独立图层上绘制（不直接污染 canvas，便于整体控制透明度）
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # 描边宽度（像素）：stroke_width <= 0 或 color_mode 时【完全不描边】（纯填充）。
    # 注意这里不能用 max(1, ...) —— 否则 stroke_width=0 也会画出 1px 外扩描边，
    # 导致"想调细却永远调不到 0"。
    sw = 0 if color_mode else max(0, int(stroke_width))

    # 3a) 先画全部描边：按 2 倍宽度绘制（Pillow 是居中描边，2 倍才等于外扩 sw 像素），
    #     字芯与描边同色；必须"全部描边画完再画全部填充"，避免相邻分段互相压盖
    if sw > 0:
        x = x0
        for run, font, w in segs:
            draw.text((x, baseline_y), run, font=font, anchor="ls",
                      fill=stroke_fill,
                      stroke_width=sw * 2,
                      stroke_fill=stroke_fill)
            x += w

    # 3b) 再画全部填充（始终执行）
    x = x0
    for run, font, w in segs:
        draw.text((x, baseline_y), run, font=font, anchor="ls", fill=fill)
        x += w

    # 4) 整体不透明度
    if opacity < 1.0:
        alpha = layer.getchannel("A").point(lambda a: int(a * max(0.0, opacity)))
        layer.putalpha(alpha)

    # 5) 合成到目标画布（layer 自身 alpha 作为蒙版，等价一次 alpha 合成）
    canvas.paste(layer, (0, 0), layer)
    return total_w
