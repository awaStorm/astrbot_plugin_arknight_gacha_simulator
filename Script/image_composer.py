# -*- coding: utf-8 -*-
"""
image_composer.py - 抽卡十连图合成器（插件实际使用版）

由 Generator_test/image_composer.py 100% 复制合成逻辑（图层顺序、光效布局、
构图参数、程序生成的光晕/小亮条/星点着色等均与测试版完全一致）。
仅做两处适配：
  1. 构图参数从 composer_config.py 读取（对应 Generator_test/config.py）。
  2. 静态素材路径改为插件实际使用的素材目录（见 composer_config.py）。

图层顺序（从底到顶）：
  1. 黑底实底 (BG_BLACK_BASE)
  2. 背景底图 (alpha_composite 到画布)
  3. 卡牌底框 (back_low_* / back_four / back_five)
  4. 光效层 (4★/5★/6★ 光柱、光环、光晕、点阵、程序生成光晕/小亮条)
  5. 角色立绘 (半身像，缩放 + 底部切边)
  6. 职业图标
  7. 星级标
"""

import json
import os

from PIL import Image, ImageChops, ImageEnhance

import composer_config as cfg


# ---------------------------------------------------------------------------
#  开关常量（独立于 composer_config.py，避免改动已调整好的构图参数）
# ---------------------------------------------------------------------------
# 是否在相邻卡片之间绘制分隔条 (sprite_avg_cutscene.png)。
ENABLE_SEPARATOR = False


# ---------------------------------------------------------------------------
#  工具：安全加载
# ---------------------------------------------------------------------------
def _load_image(path: str) -> Image.Image:
    """加载图片为 RGBA，失败抛异常（生产环境素材必须齐全）"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"素材缺失: {path}")
    return Image.open(path).convert("RGBA")


def _find_image(filenames, search_dirs):
    """在多个候选目录中按顺序查找素材文件，返回第一个存在的路径；全部缺失返回 None"""
    for d in search_dirs:
        for fn in filenames:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return p
    return None


# ---------------------------------------------------------------------------
#  工具：图层混合（透明度 + 混合模式）
# ---------------------------------------------------------------------------
def _blend_onto(canvas: Image.Image, overlay: Image.Image,
                opacity: float = 1.0, blend_mode: str = "NORMAL"):
    """
    把 overlay 按 opacity 透明度与 blend_mode 混合模式合成到 canvas 上（就地修改 canvas）。

    blend_mode: "NORMAL" 普通 alpha 合成 / "SCREEN" 滤色 / "MULTIPLY" 正片叠底 / "OVERLAY" 叠加
    """
    if opacity >= 1.0 and blend_mode == "NORMAL":
        canvas.paste(overlay, (0, 0), overlay)
        return

    base = canvas.convert("RGBA")
    ovl = overlay.convert("RGBA")

    # 1. 颜色混合
    rgb_base = base.convert("RGB")
    rgb_ovl = ovl.convert("RGB")
    if blend_mode == "SCREEN":
        mixed = ImageChops.screen(rgb_base, rgb_ovl)
    elif blend_mode == "MULTIPLY":
        mixed = ImageChops.multiply(rgb_base, rgb_ovl)
    elif blend_mode == "OVERLAY":
        mixed = ImageChops.overlay(rgb_base, rgb_ovl)
    else:
        mixed = rgb_ovl.copy()

    # 2. 组装混合后的 RGBA（alpha 取 overlay 的 alpha）
    blended = mixed.convert("RGBA")
    blended.putalpha(ovl.getchannel("A"))

    # 3. 应用透明度
    if opacity < 1.0:
        blended.putalpha(blended.getchannel("A").point(lambda a: int(a * opacity)))

    # 4. 合成回 canvas
    canvas.paste(Image.alpha_composite(base, blended), (0, 0))


# ---------------------------------------------------------------------------
#  工具：星点光效 (star_light) 整体渐变着色 + 程序生成紫色光晕
# ---------------------------------------------------------------------------
def _tint_star_light(img: Image.Image) -> Image.Image:
    """整体渐变着色 + 程序生成光晕。参数来自 config.STAR_LIGHT_COLOR。"""
    from PIL import Image as _I
    img = img.convert("RGBA")
    w, h = img.size
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    max_d = (cx * cx + cy * cy) ** 0.5
    if max_d <= 0:
        return img

    cfg_star = getattr(cfg, "STAR_LIGHT_COLOR", {})
    purple = cfg_star.get("purple", (168, 80, 255))
    white_radius = float(cfg_star.get("white_radius", 0.35))
    center_power = float(cfg_star.get("center_power", 1.5))
    halo_enabled = bool(cfg_star.get("halo_enabled", True))
    halo_scale = float(cfg_star.get("halo_scale", 2.5))
    halo_opacity = float(cfg_star.get("halo_opacity", 0.4))
    halo_softness = float(cfg_star.get("halo_softness", 1.0))

    # 防御
    white_radius = max(0.0, min(white_radius, 0.95))
    if center_power <= 0:
        center_power = 1.0
    inv_power = 1.0 / center_power
    # 有效过渡半径(整体渐变到纯紫的归一化范围)
    effective = max(0.05, 1.0 - white_radius * 0.9)
    d_r = 255 - purple[0]
    d_g = 255 - purple[1]
    d_b = 255 - purple[2]

    # ---- numpy 向量化(主路径) ----
    try:
        import numpy as np
        ys, xs = np.indices((h, w))
        d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / max_d   # 归一化距离 [0,1]
        # 整体平滑渐变(无硬边)
        d_norm = np.clip(d / effective, 0.0, 1.0)
        white_factor = 1.0 - d_norm ** inv_power                # 中心=1纯白, 边缘=0纯紫
        # 颜色 = 紫 + (白-紫)*white_factor
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[:, :, 0] = np.clip(purple[0] + d_r * white_factor, 0, 255)
        out[:, :, 1] = np.clip(purple[1] + d_g * white_factor, 0, 255)
        out[:, :, 2] = np.clip(purple[2] + d_b * white_factor, 0, 255)
        out[:, :, 3] = np.asarray(img)[:, :, 3]                 # alpha 保留原扩散形状
        ball = _I.fromarray(out, "RGBA")

        # ---- 程序生成紫色光晕(halo)并叠加在光球下方 ----
        if halo_enabled and halo_opacity > 0:
            ys2, xs2 = np.indices((h, w))
            d_h = np.sqrt((xs2 - cx) ** 2 + (ys2 - cy) ** 2) / max_d  # 归一化距离 [0,1]
            # 光晕 alpha：中心最强,向外柔和衰减
            halo_alpha = (halo_opacity * (1.0 - d_h ** max(halo_scale, 0.1))).astype(np.float32)
            halo_arr = np.zeros((h, w, 4), dtype=np.uint8)
            halo_arr[:, :, 0] = purple[0]
            halo_arr[:, :, 1] = purple[1]
            halo_arr[:, :, 2] = purple[2]
            halo_arr[:, :, 3] = np.clip(halo_alpha * 255, 0, 255).astype(np.uint8)
            halo = _I.fromarray(halo_arr, "RGBA")
            # 把光球叠加到光晕上(halo 在底, ball 在上)
            halo.alpha_composite(ball, (0, 0))
            return halo
        return ball

    except ImportError:
        pass

    # ---- 回退路径(无 numpy，逐像素) ----
    def _wf(dist):
        d_n = max(0.0, min(1.0, dist / effective))
        return 1.0 - d_n ** inv_power

    px = img.load()
    for y in range(h):
        for x in range(w):
            a = px[x, y][3]
            if a == 0:
                continue
            dx = (x - cx) / max_d
            dy = (y - cy) / max_d
            wf = _wf((dx * dx + dy * dy) ** 0.5)
            r = int(purple[0] + d_r * wf)
            g = int(purple[1] + d_g * wf)
            b = int(purple[2] + d_b * wf)
            px[x, y] = (r, g, b, a)
    return img


# ---------------------------------------------------------------------------
#  工具：dianzhen 网点纹理整体着色 (dots tint)
# ---------------------------------------------------------------------------
def _tint_dots(img: Image.Image, color: tuple) -> Image.Image:
    """把网点纹理整体染成 color 颜色, 保留 alpha 形状"""
    img = img.convert("RGBA")
    w, h = img.size
    try:
        import numpy as np
        arr = np.asarray(img)
        out = np.empty_like(arr)
        out[:, :, 0] = color[0]
        out[:, :, 1] = color[1]
        out[:, :, 2] = color[2]
        out[:, :, 3] = arr[:, :, 3]      # 保留原 alpha(网点形状)
        return Image.fromarray(out, "RGBA")
    except ImportError:
        pass
    # 回退逐像素
    px = img.load()
    for y in range(h):
        for x in range(w):
            a = px[x, y][3]
            if a == 0:
                continue
            px[x, y] = (color[0], color[1], color[2], a)
    return img


# ---------------------------------------------------------------------------
#  程序生成: 光柱顶部亮渐变光晕 (5★/6★ 通用)
# ---------------------------------------------------------------------------
def _gen_top_glow(star_level: int = 6) -> Image.Image:
    cfg_key = "STAR_5_TOP_GLOW" if star_level == 5 else "STAR_6_TOP_GLOW"
    g = getattr(cfg, cfg_key, {})
    w, h = g["size"]
    color_bright = g["color_bright"]
    color_dark = g["color_dark"]
    opacity = float(g.get("opacity", 0.8))
    try:
        import numpy as np
        # 1. 垂直颜色渐变 (y轴)
        t_y = np.linspace(1.0, 0.0, h)[:, None]
        r = (color_dark[0] + (color_bright[0] - color_dark[0]) * t_y).astype(np.uint8)
        gg = (color_dark[1] + (color_bright[1] - color_dark[1]) * t_y).astype(np.uint8)
        b = (color_dark[2] + (color_bright[2] - color_dark[2]) * t_y).astype(np.uint8)

        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[:, :, 0] = r
        arr[:, :, 1] = gg
        arr[:, :, 2] = b

        # 2. 垂直 Alpha 渐变 (y轴)
        a_y = np.linspace(0.0, opacity, h)[:, None]

        # 3. 水平 Alpha 渐变 (x轴: 中心1.0, 两侧0.0 柔和过渡)
        t_x = np.abs(np.linspace(-1.0, 1.0, w))[None, :]
        a_x = np.cos(t_x * np.pi / 2)  # 余弦柔和衰减

        # 结合 x 与 y 的 Alpha 衰减
        a_combined = (a_y * a_x * 255).astype(np.uint8)
        arr[:, :, 3] = a_combined

        return Image.fromarray(arr, "RGBA")
    except ImportError:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = img.load()
        for y in range(h):
            f = 1.0 - y / max(h - 1, 1)
            rr = int(color_dark[0] + (color_bright[0] - color_dark[0]) * f)
            gg = int(color_dark[1] + (color_bright[1] - color_dark[1]) * f)
            bb = int(color_dark[2] + (color_bright[2] - color_dark[2]) * f)
            a = int((1.0 - f) * opacity * 255)
            for x in range(w):
                px[x, y] = (rr, gg, bb, a)
        return img


# ---------------------------------------------------------------------------
#  程序生成: 光柱内随机小亮条 (5★/6★ 通用, 第二张参考图效果)
# ---------------------------------------------------------------------------
def _gen_sparkles(star_level: int = 5, seed=None) -> Image.Image:
    import random
    s = cfg.SPARKLES_CONFIG
    # 亮条生成范围取对应星级的 clip_box 的 w/h (与裁剪范围一致, 不重复定义)
    key = f"star_{star_level}_sparkles"
    sparkle_layout = cfg.LIGHT_LAYOUT.get(star_level, {}).get(key, {})
    clip_box = sparkle_layout.get("clip_box", {})
    beam_w = int(clip_box.get("w", 400))
    beam_h = int(clip_box.get("h", 565))
    count = s["count"]
    # seed 优先用调用方传入(如干员名): 让每张卡不同但同一张卡稳定;
    # 缺省时回退到配置里的固定 seed, 保持可复现。
    if seed is None:
        seed = s["seed"]
    elif isinstance(seed, str):
        # 字符串种子转成稳定整数, 避免受 PYTHONHASHSEED 影响导致跨进程分布漂移
        try:
            import zlib
            seed = zlib.crc32(seed.encode("utf-8"))
        except Exception:
            seed = sum(seed.encode("utf-8"))
    bar_w_min, bar_w_max = s["bar_width"]
    bar_h_min, bar_h_max = s["bar_height"]
    color = s["color"]
    a_min, a_max = s["alpha"]

    img = Image.new("RGBA", (beam_w, beam_h), (0, 0, 0, 0))
    px = img.load()
    rng = random.Random(seed)
    exclude_zones = s.get("exclude_zone")   # 不生成区域列表
    for _ in range(count):
        bw = rng.randint(bar_w_min, bar_w_max)
        bh = rng.randint(bar_h_min, bar_h_max)
        # 中心位置在矩形内, 但亮条不超出范围, 且避开 exclude_zone
        max_attempt = 50   # 避免无限循环
        for _attempt in range(max_attempt):
            cx = rng.randint(bw // 2, beam_w - bw // 2 - 1)
            cy = rng.randint(bh // 2, beam_h - bh // 2 - 1)
            if exclude_zones:
                inside = any(
                    ez["x"] <= cx < ez["x"] + ez["w"] and
                    ez["y"] <= cy < ez["y"] + ez["h"]
                    for ez in exclude_zones
                )
                if inside:
                    continue   # 落在不生成区域, 重新随机
            break   # 找到有效位置
        a = rng.randint(a_min, a_max)
        # 画一个中心亮、边缘渐暗的椭圆(用距离衰减)
        for dy in range(-bh // 2, bh // 2 + 1):
            for dx in range(-bw // 2, bw // 2 + 1):
                # 椭圆衰减
                d2 = (dx / max(bw / 2, 1)) ** 2 + (dy / max(bh / 2, 1)) ** 2
                if d2 > 1.0:
                    continue
                aa = int(a * (1.0 - d2))
                if aa <= 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < beam_w and 0 <= ny < beam_h:
                    px[nx, ny] = (color[0], color[1], color[2], aa)
    return img


# ---------------------------------------------------------------------------
#  工具：卡片水平切变 (CARD_SHEAR_ANGLE)
# ---------------------------------------------------------------------------
def _shear_card(img: Image.Image, angle_deg: float, x: int, y: int):
    if abs(angle_deg) < 0.001:
        return img, x, y
    import math
    theta = math.radians(angle_deg)
    tan_theta = math.tan(theta)
    w, h = img.size
    dx = int(abs(tan_theta) * h)      # 水平切变位移
    new_w = w + dx
    shift = dx if tan_theta > 0 else 0
    # PIL AFFINE 用逆矩阵: x = x' - tanθ·y'
    shear_img = img.transform(
        (new_w, h), Image.AFFINE,
        (1.0, -tan_theta, shift, 0.0, 1.0, 0.0),
        resample=Image.BICUBIC,
    )
    return shear_img, x, y


# ---------------------------------------------------------------------------
#  背景准备（与原版 _prepare_background 一致）
# ---------------------------------------------------------------------------
def _prepare_background(img: Image.Image) -> Image.Image:
    iw, ih = img.size
    if iw == ih and iw >= cfg.SRC_POT_SIZE:
        crop_top = (iw - cfg.SRC_EFFECTIVE_HEIGHT) // 2
        img = img.crop((0, crop_top, iw, iw - crop_top))
    if img.size != (cfg.CANVAS_WIDTH, cfg.CANVAS_HEIGHT):
        img = img.resize((cfg.CANVAS_WIDTH, cfg.CANVAS_HEIGHT), Image.LANCZOS)
    return img


# ---------------------------------------------------------------------------
#  合成器（与原版 ImageRenderer 逐方法对应）
# ---------------------------------------------------------------------------
class Composer:
    """插件实际使用的十连图合成器"""

    def __init__(self):
        self._bg = None
        self._separator = None
        self._card_backs = {}
        self._star_strips = {}
        self._light = {}
        self._professions_map = {}
        self._load_materials()

    # -- 素材加载 (全部来自插件素材目录) --
    def _load_materials(self):
        # 背景：优先加载已预合成的 16:9 背景图；缺失则回退单张前景素材
        composed_path = os.path.join(cfg.BG_DIR, cfg.BACKGROUND_FILE)
        if not os.path.isfile(composed_path):
            composed_path = _find_image([cfg.BACKGROUND_FILE], [cfg.BG_DIR])
        self._bg = _load_image(composed_path) if composed_path else None
        if self._bg is None:
            fallback = _find_image([cfg.BACKGROUND_FALLBACK], [cfg.BG_DIR])
            if fallback:
                self._bg = _load_image(fallback)

        sep_path = os.path.join(cfg.BG_DIR, cfg.SEPARATOR_FILE)
        if not os.path.isfile(sep_path):
            sep_path = _find_image([cfg.SEPARATOR_FILE], [cfg.BG_DIR])
        self._separator = _load_image(sep_path) if sep_path else None

        for star, fname in cfg.CARD_BACK_FILES.items():
            p = _find_image([fname], [cfg.CARD_DIR])
            self._card_backs[star] = _load_image(p) if p else None

        for star, fname in cfg.STAR_STRIP_FILES.items():
            p = _find_image([fname], [cfg.STAR_DIR])
            self._star_strips[star] = _load_image(p) if p else None

        for key, fname in cfg.LIGHT_FILES.items():
            # 光效贴图先查 TEXTURE_DIR(state)，再查 BG_DIR(素材根, 如 trail_06)
            p = _find_image([fname], [cfg.TEXTURE_DIR, cfg.BG_DIR])
            self._light[key] = _load_image(p) if p else None

        # 注册程序生成的光效(不依赖文件素材), 5★/6★ 通用
        for star in (5, 6):
            lay = cfg.LIGHT_LAYOUT.get(star, {})
            if "star_6_top_glow" in lay:
                self._light["star_6_top_glow"] = _gen_top_glow(6)
            if "star_5_top_glow" in lay:
                self._light["star_5_top_glow"] = _gen_top_glow(5)
            if f"star_{star}_sparkles" in lay:
                self._light[f"star_{star}_sparkles"] = _gen_sparkles(star)

        self._load_profession_map()

    def _load_profession_map(self):
        """从 characters_raw.json 读取 干员名 -> 职业"""
        raw_path = os.path.join(cfg.RAW_DIR, "characters_raw.json")
        if not os.path.isfile(raw_path):
            return
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("cargoquery", []):
                title = item.get("title", {})
                name = title.get("cn", "")
                prof = title.get("profession", "")
                if name and prof:
                    self._professions_map[name] = prof
        except Exception:
            pass

    def get_profession(self, name: str) -> str:
        return self._professions_map.get(name, "")

    # -- 单卡合成（与原版 _composite_card 一致） --
    def _composite_card(self, char_name: str, rarity: int) -> Image.Image:
        """
        合成单张角色卡片。图层顺序（从底到顶）：
        1. 卡槽底  2. 光效层  3. 半身像  4. 职业图标  5. 星级标
        """
        star_level = rarity

        # --- 1. 卡槽底 ---
        card_back = self._card_backs.get(rarity)
        if not card_back:
            card_back = self._card_backs.get(3)  # fallback: 3★ 底
        if not card_back:
            return None

        card_w, card_h = card_back.size
        card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        card.paste(card_back, (0, 0), card_back)

        # --- 1.4 卡背渐变色 (仅对 6★ 生效, 由 CARD_GRADIENT 控制) ---
        if star_level == 6 and cfg.CARD_GRADIENT.get("enabled", False):
            card = self._apply_card_gradient(card)

        # 注：大部分光效层移到画布级合成（见 compose_ten_pull），以便可溢出卡片且垫在卡背下层。
        #     但标记了 on_card=True 的光效(如 dianzhen 网点)在卡片内部绘制:
        #     位于【卡背之上、半身像之下】。

        # --- 1.5 卡片内层光效 (on_card, 如 dianzhen 网点) ---
        self._apply_on_card_effects(card, star_level, card_w, card_h)

        # --- 2. 半身像 ---
        portrait_path = os.path.join(cfg.PORTRAIT_DIR, f"{char_name}.png")
        if os.path.isfile(portrait_path):
            portrait = _load_image(portrait_path)
            # 缩放至卡片宽度 * PORTRAIT_SCALE
            pw = int(card_w * cfg.PORTRAIT_SCALE)
            ph = int(portrait.height * (pw / portrait.width))
            portrait = portrait.resize((pw, ph), Image.LANCZOS)

            # 水平居中(可用 AVATAR_OFFSET_X 偏移)，垂直底部对齐(底部留白给职业图标,可偏移)
            px = (card_w - pw) // 2 + cfg.AVATAR_OFFSET_X
            py = card_h - ph - cfg.PORTRAIT_BOTTOM_MARGIN + cfg.AVATAR_OFFSET_Y

            if cfg.AVATAR_CROP_TO_CARD:
                # 精确裁剪：把半身像裁剪到卡片边界内(含可调边距)
                card = self._paste_portrait_cropped(card, portrait, px, py)
            else:
                # 不裁剪：半身像允许溢出卡片(顶部/左右超出部分保留)
                card.paste(portrait, (px, py), portrait)

        # --- 4. 职业图标 ---
        # 若职业图标作为独立层溢出显示,则不在卡片内部绘制(由画布层绘制)
        if not cfg.PROFESSION_ICON_OVERFLOW:
            prof_icon = self._make_profession_icon(char_name)
            if prof_icon:
                icon_w, icon_h = prof_icon.size
                if cfg.PROFESSION_ICON_CENTER_X:
                    prof_x = (card_w - icon_w) // 2
                else:
                    prof_x = cfg.PROFESSION_ICON_X
                prof_y = card_h - icon_h - cfg.PROFESSION_ICON_BOTTOM
                card.paste(prof_icon, (prof_x, prof_y), prof_icon)

        # --- 5. 星级标 ---
        # 若星级标作为独立层溢出显示,则不在卡片内部绘制(由画布层绘制)
        if not cfg.STAR_STRIP_OVERFLOW:
            strip = self._make_star_strip(star_level)
            if strip:
                sw, sh = strip.size
                if cfg.STAR_STRIP_CENTER:
                    sx = (card_w - sw) // 2
                else:
                    sx = 0
                sy = cfg.STAR_STRIP_TOP
                card.paste(strip, (sx, sy), strip)

        return card

    # -- 生成星级标图像(按每颗星固定大小,宽度随星数变化) --
    def _make_star_strip(self, star_level: int):
        """生成缩放后的星级标图像(返回 RGBA,或 None)"""
        star_strip = self._star_strips.get(star_level)
        if not star_strip:
            return None
        sw, sh = star_strip.size
        n_stars = max(1, star_level)
        star_w = cfg.STAR_STAR_SIZE
        star_h = int(sh * (star_w / (sw / n_stars)))
        gap = cfg.STAR_STRIP_STAR_GAP
        new_sw = n_stars * star_w + (n_stars - 1) * gap
        new_sh = star_h
        return star_strip.resize((new_sw, new_sh), Image.LANCZOS)

    # -- 画布层绘制星级标(独立层,可溢出卡片) --
    def _draw_star_strip_on_canvas(self, canvas, star_level, card_x, card_y, card_w, card_h):
        """把星级标作为独立层画到画布上,以卡片顶部为基准,可溢出卡片框"""
        strip = self._make_star_strip(star_level)
        if not strip:
            return
        sw, sh = strip.size
        if cfg.STAR_STRIP_CENTER:
            sx = card_x + (card_w - sw) // 2
        else:
            sx = card_x
        sy = card_y + cfg.STAR_STRIP_TOP   # 相对卡片顶部(负数=上移到卡片外)
        canvas.paste(strip, (int(sx), int(sy)), strip)

    # -- 半身像精确裁剪(裁剪到卡片内,含可调边距) --
    def _paste_portrait_cropped(self, card, portrait, px, py):
        """
        把半身像贴到卡片上,并按 AVATAR_CROP_* 边距精确裁剪到卡片边界内。
        - 正边距 = 额外向内多裁
        - 负边距 = 允许立绘超出卡片边界多少
        返回新的 card。
        """
        card_w, card_h = card.size
        # 先把立绘贴到一张与卡片同尺寸的透明层上
        tmp = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        tmp.paste(portrait, (px, py), portrait)

        # 构造裁剪 mask: 卡片边界(±边距)内为 255, 之外为 0
        crop_top = max(0, int(cfg.AVATAR_CROP_TOP))
        crop_bottom = max(0, int(cfg.AVATAR_CROP_BOTTOM))
        crop_left = max(0, int(cfg.AVATAR_CROP_LEFT))
        crop_right = max(0, int(cfg.AVATAR_CROP_RIGHT))
        box = (
            min(crop_left, card_w - 1), min(crop_top, card_h - 1),
            max(card_w - crop_right, 1), max(card_h - crop_bottom, 1),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            box = (0, 0, card_w, card_h)
        mask = Image.new("L", (card_w, card_h), 0)
        mask.paste(255, box)

        # 用 mask 裁剪 tmp 的 alpha
        r, g, b, a = tmp.split()
        a = ImageChops.multiply(a, mask)
        cropped = Image.merge("RGBA", (r, g, b, a))

        # 合成回卡片
        return Image.alpha_composite(card, cropped)

    # -- 生成职业图标图像(按 PROFESSION_ICON_SIZE 缩放) --
    def _make_profession_icon(self, char_name: str):
        """生成缩放后的职业图标(返回 RGBA,或 None)"""
        profession = self.get_profession(char_name)
        if not profession:
            return None
        prof_path = os.path.join(cfg.PROF_DIR, f"{profession}.png")
        if not os.path.isfile(prof_path):
            return None
        prof_icon = _load_image(prof_path)
        return prof_icon.resize(
            (cfg.PROFESSION_ICON_SIZE, cfg.PROFESSION_ICON_SIZE), Image.LANCZOS)

    # -- 画布层绘制职业图标(独立层,可溢出卡片底部) --
    def _draw_profession_on_canvas(self, canvas, char_name, card_x, card_y, card_w, card_h):
        """把职业图标作为独立层画到画布上,以卡片底部为基准,可溢出卡片框"""
        icon = self._make_profession_icon(char_name)
        if not icon:
            return
        icon_w, icon_h = icon.size
        if cfg.PROFESSION_ICON_CENTER_X:
            sx = card_x + (card_w - icon_w) // 2
        else:
            sx = card_x + cfg.PROFESSION_ICON_X
        # 底部定位: 卡片底部 + PROFESSION_ICON_BOTTOM (负数=溢出卡片底部)
        sy = card_y + card_h - icon_h - cfg.PROFESSION_ICON_BOTTOM
        canvas.paste(icon, (int(sx), int(sy)), icon)

    # -- 调试: 画出该星级所有带 clip_box 光效的矩形边框 --
    def _draw_light_bounds(self, canvas, star_level, card_w, card_h, card_center):
        """把 LIGHT_LAYOUT 中带 clip_box 的光效矩形边框画到画布上(用于调试范围)"""
        try:
            from PIL import ImageDraw
        except ImportError:
            return
        dbg = getattr(cfg, "DEBUG_SHOW_BOUNDS", {})
        color = dbg.get("color", (255, 0, 255))
        width = dbg.get("width", 1)
        layout = cfg.LIGHT_LAYOUT.get(star_level, {})
        cx_, cy_ = card_center
        draw = ImageDraw.Draw(canvas)
        for key, params in layout.items():
            clip_box = params.get("clip_box")
            if not clip_box:
                continue
            cbw = int(clip_box.get("w", card_w))
            cbh = int(clip_box.get("h", card_h))
            box = (
                int(cx_ + clip_box.get("ox", 0) - cbw / 2),
                int(cy_ + clip_box.get("oy", 0) - cbh / 2),
                int(cx_ + clip_box.get("ox", 0) + cbw / 2),
                int(cy_ + clip_box.get("oy", 0) + cbh / 2),
            )
            draw.rectangle(box, outline=color, width=width)
            # 在边框左上角标注 key 名
            draw.text((box[0], box[1] - 12), key, fill=color)

    # -- 光效应用（完全由 config.LIGHT_LAYOUT 驱动） --
    def _apply_light_effects(self, canvas: Image.Image, star_level: int,
                             card_w: int, card_h: int, ref_center: tuple = None,
                             char_name: str = None):
        """
        按星级叠加光效。每张光效的位置/尺寸/透明度/混合均由
        config.LIGHT_LAYOUT 中对应星级的配置决定。

        - 若 ref_center 为 None：贴到 canvas（此时为卡片内部，center=卡片中心）
        - 若 ref_center 给定画布坐标：贴到画布上，以该点为中心（可溢出卡片）
        - char_name: 当前干员名, 用于让小亮条(sparkles)按干员名随机分布,
          达到每张卡不同、同一张卡稳定的效果; 缺省时用共享/固定分布。
        """
        layout = cfg.LIGHT_LAYOUT.get(star_level)
        if not layout:
            return
        # 图层顺序按 LIGHT_LAYOUT 中定义的顺序（先定义的在底层）
        # 注意:
        #   on_card=True 的光效(如 dianzhen 网点)在卡片内部绘制(_composite_card)
        #   above_card=True 的光效(如 6★光柱)在卡片之上的独立层绘制(_apply_light_above_card)
        #   两者都不在此画布下层重复绘制。
        for key, params in layout.items():
            if params.get("on_card") or params.get("above_card"):
                continue
            img = self._light.get(key)
            # 小亮条: 传入干员名作为种子动态生成, 实现每张卡随机分布
            if key in ("star_5_sparkles", "star_6_sparkles") and char_name:
                img = _gen_sparkles(star_level, seed=char_name)
            if img:
                # star_light 为纯白光球，先做径向渐变着色（中心白、边缘紫）
                if key == "star_light":
                    img = _tint_star_light(img)
                self._paste_light(canvas, img, card_w, card_h, params, ref_center)

    # -- 卡背渐变色(仅6★, 由 CARD_GRADIENT 控制) --
    def _apply_card_gradient(self, card: Image.Image) -> Image.Image:
        """
        在卡背上叠加一层渐变图层, 让 6★ 卡面呈现渐变色调。
        参数来自 config.CARD_GRADIENT: color_top/color_bottom/opacity/direction/
        blend_mode/pos/size。pos/size 限定渐变位置和范围(相对卡片中心),
        区域外 alpha=0,避免跑出卡片范围。
        """
        g = cfg.CARD_GRADIENT
        card_w, card_h = card.size
        top = g.get("color_top", (120, 60, 200))
        bottom = g.get("color_bottom", (40, 10, 90))
        opacity = float(g.get("opacity", 0.5))
        direction = g.get("direction", "vertical")
        blend_mode = g.get("blend_mode", "NORMAL")
        # 渐变位置/范围(相对卡片中心)
        pos = g.get("pos", None)         # (x, y) 起始偏移; None=覆盖整张卡
        size = g.get("size", None)       # (w, h) 范围; None=覆盖整张卡

        # 计算渐变在卡片上的实际区域(像素坐标)
        if pos is not None and size is not None:
            cx_c = card_w / 2.0
            cy_c = card_h / 2.0
            gw = size[0] if size[0] else card_w          # 渐变宽度
            gh = size[1] if size[1] else card_h          # 渐变高度
            x0 = int(cx_c + pos[0] - gw / 2)
            x1 = int(x0 + gw)
            y0 = int(cy_c + pos[1])
            y1 = int(y0 + gh)
        else:
            x0, y0, x1, y1 = 0, 0, card_w, card_h

        # 生成渐变 RGBA 图层(只在 [x0,x1)x[y0,y1) 范围内有色, 区域外 alpha=0)
        try:
            import numpy as np
            grad = np.zeros((card_h, card_w, 4), dtype=np.float32)
            if direction == "radial":
                ys, xs = np.indices((card_h, card_w))
                rcx = (x0 + x1) / 2.0
                rcy = (y0 + y1) / 2.0
                rmax = max((x1 - x0) / 2.0, (y1 - y0) / 2.0, 1)
                d = np.sqrt((xs - rcx) ** 2 + (ys - rcy) ** 2) / rmax
                d = np.clip(d, 0.0, 1.0)
                mask_in = (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
                t = d                          # (card_h, card_w)
            else:
                # 垂直渐变: 上=top, 下=bottom
                ys_grid = np.broadcast_to(
                    np.arange(card_h)[:, None], (card_h, card_w)).astype(np.float32)
                xs_grid = np.broadcast_to(
                    np.arange(card_w)[None, :], (card_h, card_w)).astype(np.float32)
                t = np.zeros((card_h, card_w), dtype=np.float32)
                # 必须同时约束 x ∈ [x0, x1) 和 y ∈ [y0, y1)
                mask_in = (ys_grid >= y0) & (ys_grid < y1) & \
                          (xs_grid >= x0) & (xs_grid < x1)
                if y1 > y0:
                    t = np.where(mask_in, (ys_grid - y0) / (y1 - y0), 0.0)
            grad[..., 0] = (top[0] + (bottom[0] - top[0]) * t)
            grad[..., 1] = (top[1] + (bottom[1] - top[1]) * t)
            grad[..., 2] = (top[2] + (bottom[2] - top[2]) * t)
            grad[..., 3] = np.where(mask_in, opacity * 255.0, 0.0)
            grad_img = Image.fromarray(grad.astype(np.uint8), "RGBA")
        except ImportError:
            # 回退: 简单垂直渐变
            grad_img = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
            px = grad_img.load()
            for y in range(card_h):
                in_range = y0 <= y < y1
                if not in_range:
                    continue
                f = (y - y0) / max(y1 - y0, 1)
                r = int(top[0] + (bottom[0] - top[0]) * f)
                gg = int(top[1] + (bottom[1] - top[1]) * f)
                b = int(top[2] + (bottom[2] - top[2]) * f)
                a = int(opacity * 255)
                for x in range(x0, x1):
                    px[x, y] = (r, gg, b, a)

        # 用 blend 模式叠加渐变到卡背
        tmp = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        tmp.paste(grad_img, (0, 0), grad_img)
        _blend_onto(card, tmp, opacity=1.0, blend_mode=blend_mode)
        return card

    # -- 卡片内层光效 (on_card=True, 如 dianzhen 网点) --
    def _apply_on_card_effects(self, card: Image.Image, star_level: int,
                               card_w: int, card_h: int):
        """
        在卡片内部绘制标记了 on_card=True 的光效(如 dianzhen 网点纹理)。
        图层位置: 卡背之上、半身像之下。位置/大小/透明度由 LIGHT_LAYOUT 决定。
        传入 ref_center(卡片中心),使 clip_to_ref=True 的光效可被裁剪到卡片边界内(被框住)。
        """
        layout = cfg.LIGHT_LAYOUT.get(star_level)
        if not layout:
            return
        card_center = (card_w / 2.0, card_h / 2.0)
        for key, params in layout.items():
            if not params.get("on_card"):
                continue
            img = self._light.get(key)
            if img:
                # 传入 ref_center=卡片中心, 使 clip_to_ref 裁剪到卡片边界生效
                self._paste_light(card, img, card_w, card_h, params, card_center)

    # -- 卡片之上独立层光效 (above_card=True, 如 6★光柱) --
    def _apply_light_above_card(self, canvas: Image.Image, star_level: int,
                                card_w: int, card_h: int, ref_center: tuple):
        """
        绘制标记了 above_card=True 的光效(如 6★光柱)在卡片之上。
        这些光效以卡片中心为锚点画到画布上,可溢出卡片框(不被卡片框住)。
        必须在卡片绘制之后调用,使光效盖在卡片之上。
        """
        layout = cfg.LIGHT_LAYOUT.get(star_level)
        if not layout:
            return
        for key, params in layout.items():
            if not params.get("above_card"):
                continue
            img = self._light.get(key)
            if img:
                self._paste_light(canvas, img, card_w, card_h, params, ref_center)

    @staticmethod
    def _paste_light(canvas: Image.Image, overlay: Image.Image,
                     ref_w: int, ref_h: int, params: dict,
                     ref_center: tuple = None):
        """
        按 params 布局字典把光效贴到 canvas 上。

        - ref_w, ref_h : 参考尺寸（通常是卡片尺寸），用于 scale / scale_w / scale_h 计算
        - ref_center   : 参考中心点在 canvas 上的坐标 (x, y)。
                         传入时，光效以该点为中心定位（支持溢出卡片 / 画布任意位置）；
                         为 None 时，中心取 ref_w/2, ref_h/2（即卡片内部中心）。
        - params 支持的字段（详见 composer_config.LIGHT_LAYOUT 注释）：
          pos, anchor, size, scale, scale_w, scale_h, opacity, blend_mode, clip_to_ref

        定位规则：
          anchor == "center"   -> pos 是光效中心相对 ref_center 的偏移（默认，最直观）
          anchor == "topleft"  -> pos 是光效左上角相对 ref_center 左上角(ref_center - ref/2)的偏移

        clip_to_ref :
          True 时，把光效裁剪到 ref_w x ref_h 范围（卡片范围，超出截断）。
          默认 False，光效可溢出 ref 范围。
        """
        ow, oh = overlay.size
        anchor = params.get("anchor", "center")
        clip_to_ref = bool(params.get("clip_to_ref", False))

        # 0) 可选整体着色(tint): 把素材染成指定颜色(用于 dianzhen 网点等黑白纹理)。
        tint = params.get("tint")
        if tint is not None:
            overlay = _tint_dots(overlay, tuple(tint))

        # 1) 计算目标宽高
        size = params.get("size")
        if size:                                    # 直接指定像素宽高（可非等比拉伸）
            target_w, target_h = int(size[0]), int(size[1])
        else:
            scale = params.get("scale", 1.0)
            sw = params.get("scale_w")              # 独立宽度比例（覆盖 scale 的宽度）
            sh = params.get("scale_h")              # 独立高度比例（覆盖 scale 的高度）
            if sw is not None and sh is not None:   # 双独立拉伸（非等比）
                target_w = int(ref_w * sw)
                target_h = int(ref_h * sh)
            elif sw is not None:                    # 仅横向拉伸
                target_w = int(ref_w * sw)
                target_h = int(oh * (target_w / ow))
            elif sh is not None:                    # 仅纵向拉伸
                target_h = int(ref_h * sh)
                target_w = int(ow * (target_h / oh))
            else:                                   # 统一缩放（保持纵横比）
                target_w = int(ref_w * scale)
                target_h = int(oh * (target_w / ow))

        scaled = overlay.resize((target_w, target_h), Image.LANCZOS)

        # 1.5) 可选旋转(angle 参数, 或全局 TEXTURE_ROTATE_ANGLE)
        rotate_angle = params.get("angle")
        if rotate_angle is None:
            rotate_angle = cfg.TEXTURE_ROTATE_ANGLE
        if rotate_angle:
            scaled = scaled.rotate(rotate_angle, resample=Image.BICUBIC, expand=True)
            target_w, target_h = scaled.size   # 旋转后尺寸可能变化,更新用于定位

        # 2) 计算参考中心
        if ref_center is not None:
            center_x, center_y = ref_center
        else:
            center_x, center_y = ref_w / 2.0, ref_h / 2.0

        # 3) 计算粘贴位置
        px, py = params.get("pos", (0, 0))
        if anchor == "topleft":                     # 左上角相对参考左上角
            ref_left = center_x - ref_w / 2.0
            ref_top = center_y - ref_h / 2.0
            px = int(ref_left + px)
            py = int(ref_top + py)
        else:                                       # center：光效中心相对参考中心
            px = int(center_x - target_w / 2.0 + px)
            py = int(center_y - target_h / 2.0 + py)

        # 4) 应用透明度 + 混合模式
        #    全局 TEXTURE_OPACITY 作为乘法系数作用于每项 opacity(全局×每项)
        #    全局 TEXTURE_BLEND_MODE 在每项未指定 blend_mode 时作为默认
        base_opacity = params.get("opacity", 1.0)
        opacity = base_opacity * cfg.TEXTURE_OPACITY
        blend_mode = params.get("blend_mode", cfg.TEXTURE_BLEND_MODE)

        # 4.5) 裁剪(作用于光效自身图层 scaled, 不影响背景/其他光效)
        clip_box = params.get("clip_box")
        if ref_center is not None and (clip_box or clip_to_ref):
            cx_, cy_ = ref_center
            if clip_box:
                cbw = int(clip_box.get("w", ref_w))
                cbh = int(clip_box.get("h", ref_h))
                box = (
                    int(cx_ + clip_box.get("ox", 0) - cbw / 2),
                    int(cy_ + clip_box.get("oy", 0) - cbh / 2),
                    int(cx_ + clip_box.get("ox", 0) + cbw / 2),
                    int(cy_ + clip_box.get("oy", 0) + cbh / 2),
                )
            else:
                box = (
                    int(cx_ - ref_w / 2), int(cy_ - ref_h / 2),
                    int(cx_ + ref_w / 2), int(cy_ + ref_h / 2),
                )
            # 裁剪 scaled: 把 box 与 scaled 自身矩形(px,py,px+tw,py+th)求交,
            # box 外的像素 alpha 置 0
            sw_w, sw_h = scaled.size
            sx0, sy0 = px, py                      # scaled 在 canvas 上的左上角
            sx1, sy1 = px + sw_w, py + sw_h        # scaled 在 canvas 上的右下角
            # 与 box 求交集
            ix0 = max(sx0, box[0]); iy0 = max(sy0, box[1])
            ix1 = min(sx1, box[2]); iy1 = min(sy1, box[3])
            if ix1 > ix0 and iy1 > iy0:
                # 在 scaled 自身坐标下, box 内的相对区域
                rel = (ix0 - sx0, iy0 - sy0, ix1 - sx0, iy1 - sy0)
                cmask = Image.new("L", (sw_w, sw_h), 0)
                cmask.paste(255, rel)
                r, g, b, a = scaled.split()
                a = ImageChops.multiply(a, cmask)
                scaled = Image.merge("RGBA", (r, g, b, a))
            else:
                # 完全不相交: 整张置透明
                scaled = Image.new("RGBA", (sw_w, sw_h), (0, 0, 0, 0))

        # 5) 粘贴
        if opacity >= 1.0 and blend_mode == "NORMAL":
            # 与原版 _paste_centered_scaled 完全一致：直接按 alpha 覆盖（支持负坐标自动裁剪）
            canvas.paste(scaled, (px, py), scaled)
        else:
            # 需要透明度/混合：先把光效铺到与 canvas 同尺寸的透明临时层，再统一混合
            tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            tmp.paste(scaled, (px, py), scaled)
            _blend_onto(canvas, tmp, opacity, blend_mode)

    # -- 十连布局（与原版 _layout_ten_pull 一致） --
    def compose_ten_pull(self, results) -> Image.Image:
        """
        将 10 张角色卡片水平排列，加背景和分隔条，合成最终十连图片。
        results: [{"name": str, "rarity": int}, ...] 共 10 项
        """
        # 创建画布：最底层铺实底（颜色由 BG_BLACK_BASE 决定，避免背景素材透明区域透过）
        if cfg.BG_BLACK_BASE:
            canvas = Image.new(
                "RGBA", (cfg.CANVAS_WIDTH, cfg.CANVAS_HEIGHT), (0, 0, 0, 255))
        else:
            canvas = Image.new(
                "RGBA", (cfg.CANVAS_WIDTH, cfg.CANVAS_HEIGHT), (0, 0, 0, 0))

        # 1. 背景（裁剪 POT 填充黑边后直接使用，不 resize）
        if self._bg:
            bg = self._bg.copy()
            bg = _prepare_background(bg)
            # 背景亮度（BG_BRIGHTNESS：1.0 原样，>1 增亮，<1 压暗）
            if cfg.BG_BRIGHTNESS != 1.0:
                bg = ImageEnhance.Brightness(bg).enhance(cfg.BG_BRIGHTNESS)
            canvas = Image.alpha_composite(canvas, bg)

        # 2. 计算卡片区起始 x 坐标（居中排列）
        total_width = len(results) * cfg.CARD_WIDTH + (len(results) - 1) * cfg.CARD_GAP
        start_x = (cfg.CANVAS_WIDTH - total_width) // 2

        # 3. 逐张放置卡片
        card_w = cfg.CARD_WIDTH
        card_h = cfg.CARD_HEIGHT
        if cfg.CARD_CENTER_Y:
            card_y = (cfg.CANVAS_HEIGHT - card_h) // 2   # 垂直居中
        else:
            card_y = cfg.CARD_START_Y                    # 使用指定起始 Y

        for i, r in enumerate(results):
            star_level = int(r["rarity"])
            card = self._composite_card(r["name"], star_level)
            if card is None:
                continue

            x = start_x + i * (cfg.CARD_WIDTH + cfg.CARD_GAP)

            # 卡片在画布中的中心点（作为光效的参考锚点）
            card_center = (x + card_w / 2.0, card_y + card_h / 2.0)

            # 3a. 先贴光效层（画布级，可溢出卡片，且垫在卡片下层）
            #     传入当前干员名, 让小亮条按角色随机分布(同一角色稳定)
            self._apply_light_effects(canvas, star_level, card_w, card_h, card_center,
                                      char_name=r["name"])

            # 3a'. 调试: 画出该星级所有带 clip_box 光效的矩形边框(可视化范围)
            dbg = getattr(cfg, "DEBUG_SHOW_BOUNDS", {})
            if dbg.get("enabled", False):
                self._draw_light_bounds(canvas, star_level, card_w, card_h, card_center)

            # 3b. 再贴卡片本身（卡背 + 立绘 + 职业，覆盖在光效之上）
            scaled_card = card.resize((card_w, card_h), Image.LANCZOS)
            paste_x = x
            paste_y = card_y
            # 可选卡片切变(整排倾斜, 默认0=不切变)
            if cfg.CARD_SHEAR_ANGLE:
                scaled_card, paste_x, paste_y = _shear_card(
                    scaled_card, cfg.CARD_SHEAR_ANGLE, paste_x, paste_y)
            canvas.paste(scaled_card, (paste_x, paste_y), scaled_card)

            # 3b'''. 卡片之上的独立层光效(如 6★光柱): 盖在卡片上、可溢出卡片框
            self._apply_light_above_card(canvas, star_level, card_w, card_h, card_center)

            # 3b'. 星级标作为独立层绘制在卡片上方(可溢出卡片框,不被卡片裁剪)
            if cfg.STAR_STRIP_OVERFLOW:
                self._draw_star_strip_on_canvas(canvas, star_level, x, card_y, card_w, card_h)

            # 3b''. 职业图标作为独立层绘制在卡片底部(可溢出卡片框,不被卡片裁剪)
            if cfg.PROFESSION_ICON_OVERFLOW:
                self._draw_profession_on_canvas(
                    canvas, r["name"], x, card_y, card_w, card_h)

            # 3c. 分隔条（受 ENABLE_SEPARATOR 开关控制，且非最后一张才绘制）
            if ENABLE_SEPARATOR and i < len(results) - 1 and self._separator:
                sep = self._separator.copy()
                sep_h = card_h
                sep = sep.resize((cfg.CARD_GAP, sep_h), Image.LANCZOS)
                sep_x = x + cfg.CARD_WIDTH
                canvas.paste(sep, (sep_x, card_y), sep)

        return canvas

    # -- 保存 --
    def save(self, img: Image.Image, path: str):
        """转 RGB 丢弃 alpha，保证完全不透明后保存为 PNG"""
        img.convert("RGB").save(path, "PNG")


def compose_and_save(results, out_path: str):
    """便捷入口：合成十连图并保存到 out_path"""
    composer = Composer()
    img = composer.compose_ten_pull(results)
    composer.save(img, out_path)
    return out_path
