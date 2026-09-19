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
from collections import OrderedDict

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

import composer_config as cfg
import text_render
from camp_logo_map import CAMP_LOGO_DIR, get_camp_logo_file


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


def _tint_image(img: Image.Image, color, strength: float = 1.0) -> Image.Image:
    """
    把整张图染成指定颜色，保留原有的明暗层次与 alpha 形状。

    以原图亮度为蒙版铺一层目标色（暗处留黑），再与原色按 strength 混合：
      strength = 1.0 → 完全变为目标色（只保留原图的明暗分布）
      strength < 1.0 → 与原色渐变混合
    """
    img = img.convert("RGBA")
    base_rgb = img.convert("RGB")
    lum = base_rgb.convert("L")
    solid = Image.new("RGB", img.size, tuple(color[:3]))
    shaded = Image.composite(solid, Image.new("RGB", img.size, (0, 0, 0)), lum)
    k = max(0.0, min(float(strength), 1.0))
    out = Image.blend(base_rgb, shaded, k).convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


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


def profession_map_path() -> str:
    """干员→职业 映射的数据源路径（characters_raw.json）"""
    return os.path.join(cfg.RAW_DIR, "characters_raw.json")


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

    def __init__(self, elite1_art_dir: str = ""):
        # 精一立绘的【实际】缓存目录，由 ImageRenderer 按其画质档位注入
        # （形如 <cache>/elite1_art/original）。
        # 留空时 _load_elite1_art 会回退到 cfg.ELITE1_ART_DIR 并在其子目录中兜底查找，
        # 因此直接 Composer() 构造（如 tools/ 下的调试脚本）依然可用。
        self.elite1_art_dir = elite1_art_dir or ""
        self._bg = None
        self._separator = None
        self._card_backs = {}
        self._star_strips = {}
        self._light = {}
        self._professions_map = {}
        # 干员元信息 {干员名: {"en": 英文名, "logo": 阵营中文名, "profession": 职业}}
        self._meta_map = {}
        # 单抽 v3 元素素材缓存 {文件路径: RGBA 图像}
        self._sp3_asset_cache = {}
        # 程序生成的光柱缓存 {参数元组: RGBA 图像}
        self._sp3_beam_cache = {}
        # 精一立绘解码缓存 {干员名: RGBA 图像}，LRU 淘汰。
        # 立绘是 1024×1024 级别的 PNG，解码一次几十毫秒，十连要解 10 张，
        # 缓存后连续抽卡 / 同一干员重复出现时可直接复用。
        # 单张约 4MB，上限 12 张（≈48MB），避免长时间运行后内存无限增长。
        self._elite1_art_cache: OrderedDict = OrderedDict()
        self._elite1_art_cache_max = 12
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
        """
        从 characters_raw.json 读取 干员名 -> 职业。

        采用【清空后重建】语义：数据更新后旧条目不应残留，
        避免已改名/已修正的干员沿用陈旧职业。
        读取失败（文件缺失/解析异常）时保留原映射，不破坏已有结果。
        """
        raw_path = profession_map_path()
        if not os.path.isfile(raw_path):
            return
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        mapping = {}
        meta = {}
        for item in data.get("cargoquery", []):
            title = item.get("title", {})
            name = title.get("cn", "")
            prof = title.get("profession", "")
            if name and prof:
                mapping[name] = prof
            if name:
                meta[name] = {
                    "en": title.get("en", ""),
                    "logo": title.get("logo", ""),
                    "profession": prof,
                }
        self._professions_map = mapping
        self._meta_map = meta

    def reload_profession_map(self) -> int:
        """重新加载 干员名 -> 职业 映射（数据更新后调用），返回映射条目数"""
        self._load_profession_map()
        return len(self._professions_map)

    def get_profession(self, name: str) -> str:
        return self._professions_map.get(name, "")

    def get_en_name(self, name: str) -> str:
        """取干员英文名（缺失返回空字符串）"""
        return self._meta_map.get(name, {}).get("en", "")

    def get_camp_cn(self, name: str) -> str:
        """取干员阵营中文名（缺失返回空字符串）"""
        return self._meta_map.get(name, {}).get("logo", "")

    def get_camp_logo_path(self, name: str) -> str:
        """
        取干员阵营 logo 的本地文件路径。

        映射未命中 / 阵营为空 / 文件不存在 三种情况统一降级为罗德岛，
        且无论文件是否存在都返回路径，由调用方决定是否可绘制。
        """
        logo_file = get_camp_logo_file(self.get_camp_cn(name))
        return os.path.join(cfg.MATERIAL_DIR, CAMP_LOGO_DIR, logo_file)

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
    def _make_star_strip(self, star_level: int, zoom: float = 1.0):
        """生成缩放后的星级标图像(返回 RGBA,或 None)；zoom 用于单抽放大"""
        star_strip = self._star_strips.get(star_level)
        if not star_strip:
            return None
        sw, sh = star_strip.size
        n_stars = max(1, star_level)
        star_w = cfg.STAR_STAR_SIZE * zoom
        star_h = int(sh * (star_w / (sw / n_stars)))
        gap = cfg.STAR_STRIP_STAR_GAP * zoom
        new_sw = int(round(n_stars * star_w + (n_stars - 1) * gap))
        new_sh = max(1, star_h)
        return star_strip.resize((new_sw, new_sh), Image.LANCZOS)

    # -- 画布层绘制星级标(独立层,可溢出卡片) --
    def _draw_star_strip_on_canvas(self, canvas, star_level, card_x, card_y,
                                   card_w, card_h, zoom: float = 1.0):
        """把星级标作为独立层画到画布上,以卡片顶部为基准,可溢出卡片框"""
        strip = self._make_star_strip(star_level, zoom)
        if not strip:
            return
        sw, sh = strip.size
        if cfg.STAR_STRIP_CENTER:
            sx = card_x + (card_w - sw) // 2
        else:
            sx = card_x
        # 相对卡片顶部(负数=上移到卡片外)，偏移随卡片放大同步缩放
        sy = card_y + cfg.STAR_STRIP_TOP * zoom
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
    def _make_profession_icon(self, char_name: str, zoom: float = 1.0):
        """生成缩放后的职业图标(返回 RGBA,或 None)；zoom 用于单抽放大"""
        profession = self.get_profession(char_name)
        if not profession:
            return None
        prof_path = os.path.join(cfg.PROF_DIR, f"{profession}.png")
        if not os.path.isfile(prof_path):
            return None
        prof_icon = _load_image(prof_path)
        size = max(1, int(round(cfg.PROFESSION_ICON_SIZE * zoom)))
        return prof_icon.resize((size, size), Image.LANCZOS)

    # -- 画布层绘制职业图标(独立层,可溢出卡片底部) --
    def _draw_profession_on_canvas(self, canvas, char_name, card_x, card_y,
                                   card_w, card_h, zoom: float = 1.0):
        """把职业图标作为独立层画到画布上,以卡片底部为基准,可溢出卡片框"""
        icon = self._make_profession_icon(char_name, zoom)
        if not icon:
            return
        icon_w, icon_h = icon.size
        if cfg.PROFESSION_ICON_CENTER_X:
            sx = card_x + (card_w - icon_w) // 2
        else:
            sx = card_x + cfg.PROFESSION_ICON_X * zoom
        # 底部定位: 卡片底部 + PROFESSION_ICON_BOTTOM (负数=溢出卡片底部)
        sy = card_y + card_h - icon_h - cfg.PROFESSION_ICON_BOTTOM * zoom
        canvas.paste(icon, (int(sx), int(sy)), icon)

    # -- 调试: 画出该星级所有带 clip_box 光效的矩形边框 --
    def _draw_light_bounds(self, canvas, star_level, card_w, card_h, card_center,
                           zoom: float = 1.0):
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
            cbw = int(clip_box.get("w", card_w) * zoom)
            cbh = int(clip_box.get("h", card_h) * zoom)
            box = (
                int(cx_ + clip_box.get("ox", 0) * zoom - cbw / 2),
                int(cy_ + clip_box.get("oy", 0) * zoom - cbh / 2),
                int(cx_ + clip_box.get("ox", 0) * zoom + cbw / 2),
                int(cy_ + clip_box.get("oy", 0) * zoom + cbh / 2),
            )
            draw.rectangle(box, outline=color, width=width)
            # 在边框左上角标注 key 名
            draw.text((box[0], box[1] - 12), key, fill=color)

    # -- 光效应用（完全由 config.LIGHT_LAYOUT 驱动） --
    def _apply_light_effects(self, canvas: Image.Image, star_level: int,
                             card_w: int, card_h: int, ref_center: tuple = None,
                             char_name: str = None, zoom: float = 1.0):
        """
        按星级叠加光效。每张光效的位置/尺寸/透明度/混合均由
        config.LIGHT_LAYOUT 中对应星级的配置决定。

        - 若 ref_center 为 None：贴到 canvas（此时为卡片内部，center=卡片中心）
        - 若 ref_center 给定画布坐标：贴到画布上，以该点为中心（可溢出卡片）
        - char_name: 当前干员名, 用于让小亮条(sparkles)按干员名随机分布,
          达到每张卡不同、同一张卡稳定的效果; 缺省时用共享/固定分布。
        - zoom: 整体缩放倍率(1.0=十连原尺寸), 单抽放大卡片时传入同一倍率。
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
                self._paste_light(canvas, img, card_w, card_h, params, ref_center, zoom)

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
                                card_w: int, card_h: int, ref_center: tuple,
                                zoom: float = 1.0):
        """
        绘制标记了 above_card=True 的光效(如 6★光柱)在卡片之上。
        这些光效以卡片中心为锚点画到画布上,可溢出卡片框(不被卡片框住)。
        必须在卡片绘制之后调用,使光效盖在卡片之上。

        zoom: 整体缩放倍率(1.0=十连原尺寸), 单抽放大卡片时传入同一倍率。
        """
        layout = cfg.LIGHT_LAYOUT.get(star_level)
        if not layout:
            return
        for key, params in layout.items():
            if not params.get("above_card"):
                continue
            img = self._light.get(key)
            if img:
                self._paste_light(canvas, img, card_w, card_h, params, ref_center, zoom)

    @staticmethod
    def _paste_light(canvas: Image.Image, overlay: Image.Image,
                     ref_w: int, ref_h: int, params: dict,
                     ref_center: tuple = None, zoom: float = 1.0):
        """
        按 params 布局字典把光效贴到 canvas 上。

        - ref_w, ref_h : 参考尺寸（通常是卡片尺寸），用于 scale / scale_w / scale_h 计算
        - ref_center   : 参考中心点在 canvas 上的坐标 (x, y)。
                         传入时，光效以该点为中心定位（支持溢出卡片 / 画布任意位置）；
                         为 None 时，中心取 ref_w/2, ref_h/2（即卡片内部中心）。
        - zoom         : 整体缩放倍率（默认 1.0 = 十连原始尺寸）。
                         单抽把卡片放大时传入同一倍率，光效的 size / pos / clip_box
                         会同步放大，使其相对卡片的构图与十连完全一致。
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
        #     zoom != 1.0 时参考尺寸同步放大（scale/scale_w/scale_h 的基准随之放大）
        ref_w_z = ref_w * zoom
        ref_h_z = ref_h * zoom
        size = params.get("size")
        if size:                                    # 直接指定像素宽高（可非等比拉伸）
            target_w, target_h = int(size[0] * zoom), int(size[1] * zoom)
        else:
            scale = params.get("scale", 1.0)
            sw = params.get("scale_w")              # 独立宽度比例（覆盖 scale 的宽度）
            sh = params.get("scale_h")              # 独立高度比例（覆盖 scale 的高度）
            if sw is not None and sh is not None:   # 双独立拉伸（非等比）
                target_w = int(ref_w_z * sw)
                target_h = int(ref_h_z * sh)
            elif sw is not None:                    # 仅横向拉伸
                target_w = int(ref_w_z * sw)
                target_h = int(oh * (target_w / ow))
            elif sh is not None:                    # 仅纵向拉伸
                target_h = int(ref_h_z * sh)
                target_w = int(ow * (target_h / oh))
            else:                                   # 统一缩放（保持纵横比）
                target_w = int(ref_w_z * scale)
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

        # 3) 计算粘贴位置（偏移随 zoom 放大，保持相对卡片的构图）
        px, py = params.get("pos", (0, 0))
        px, py = px * zoom, py * zoom
        if anchor == "topleft":                     # 左上角相对参考左上角
            ref_left = center_x - ref_w_z / 2.0
            ref_top = center_y - ref_h_z / 2.0
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
                cbw = int(clip_box.get("w", ref_w) * zoom)
                cbh = int(clip_box.get("h", ref_h) * zoom)
                box = (
                    int(cx_ + clip_box.get("ox", 0) * zoom - cbw / 2),
                    int(cy_ + clip_box.get("oy", 0) * zoom - cbh / 2),
                    int(cx_ + clip_box.get("ox", 0) * zoom + cbw / 2),
                    int(cy_ + clip_box.get("oy", 0) * zoom + cbh / 2),
                )
            else:
                box = (
                    int(cx_ - ref_w_z / 2), int(cy_ - ref_h_z / 2),
                    int(cx_ + ref_w_z / 2), int(cy_ + ref_h_z / 2),
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

    # -- 画布底座（十连 / 单抽共用，保证两者底色完全一致） --
    def _build_canvas(self, width: int, height: int) -> Image.Image:
        """
        创建带背景的初始画布：
        1. 按 BG_BLACK_BASE 决定是否铺纯黑不透明实底（避免背景素材透明区域透过）；
        2. 叠加背景底图（POT 裁剪，不 resize）；
        3. 应用 BG_BRIGHTNESS 背景亮度系数。
        """
        if cfg.BG_BLACK_BASE:
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        else:
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        if self._bg:
            bg = self._bg.copy()
            bg = _prepare_background(bg)
            if bg.size != (width, height):
                bg = bg.resize((width, height), Image.LANCZOS)
            # 背景亮度（BG_BRIGHTNESS：1.0 原样，>1 增亮，<1 压暗）
            if cfg.BG_BRIGHTNESS != 1.0:
                bg = ImageEnhance.Brightness(bg).enhance(cfg.BG_BRIGHTNESS)
            canvas = Image.alpha_composite(canvas, bg)
        return canvas

    # -- 十连布局（与原版 _layout_ten_pull 一致） --
    def compose_ten_pull(self, results) -> Image.Image:
        """
        将 10 张角色卡片水平排列，加背景和分隔条，合成最终十连图片。
        results: [{"name": str, "rarity": int}, ...] 共 10 项
        """
        # 创建画布：黑底开关 + 背景 + 背景亮度（公共逻辑见 _build_canvas）
        canvas = self._build_canvas(cfg.CANVAS_WIDTH, cfg.CANVAS_HEIGHT)

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

    # -- 单抽布局（与十连同一套图层顺序，仅把这一张卡居中放大） --
    def compose_single_pull(self, result, card_fill: float = None) -> Image.Image:
        """
        合成单抽结果图：一张卡居中放大，图层顺序与十连完全一致
        （底层光效 → 卡片 → 卡片上方光效 → 溢出星级标 → 溢出职业图标）。

        单抽不是"另写一套画法"，而是把十连中【一张卡】的整块构图整体放大：
        以 CARD_WIDTH x CARD_HEIGHT 为基准算出统一倍率 zoom，卡片按 zoom 放大，
        同时把 zoom 透传给光效 / 星级标 / 职业图标，使所有元素的相对位置、相对大小、
        裁剪范围与十连中的同一张卡一致（避免单抽缺光效、缺星级标、缺职业图标）。

        result:    {"name": str, "rarity": int}
        card_fill: 卡片高度占画布高度的比例（缺省读 cfg.SINGLE_PULL_CARD_FILL）
        """
        canvas_w = cfg.CANVAS_WIDTH
        canvas_h = cfg.CANVAS_HEIGHT
        star_level = int(result["rarity"])
        char_name = result["name"]

        # 1. 画布 + 背景（与十连共用同一底座逻辑）
        canvas = self._build_canvas(canvas_w, canvas_h)

        # 2. 计算统一缩放倍率（同时受画布宽/高约束，保证卡片完整落在画布内）
        if card_fill is None:
            card_fill = getattr(cfg, "SINGLE_PULL_CARD_FILL", 0.92)
        base_w = cfg.CARD_WIDTH
        base_h = cfg.CARD_HEIGHT
        zoom = min(canvas_w * card_fill / base_w, canvas_h * card_fill / base_h)
        card_w = max(1, int(base_w * zoom))
        card_h = max(1, int(base_h * zoom))

        card_x = (canvas_w - card_w) // 2
        card_y = (canvas_h - card_h) // 2
        card_center = (card_x + card_w / 2.0, card_y + card_h / 2.0)

        # 3a. 底层光效（画布级，可溢出卡片，垫在卡片下层）
        self._apply_light_effects(
            canvas, star_level, base_w, base_h, card_center,
            char_name=char_name, zoom=zoom)

        # 3a'. 调试: 画出该星级所有带 clip_box 光效的矩形边框(可视化范围)
        dbg = getattr(cfg, "DEBUG_SHOW_BOUNDS", {})
        if dbg.get("enabled", False):
            self._draw_light_bounds(
                canvas, star_level, base_w, base_h, card_center, zoom)

        # 3b. 卡片本身（卡背 + 卡内光效 + 立绘），按 zoom 放大后居中
        card = self._composite_card(char_name, star_level)
        if card is None:
            return canvas
        scaled_card = card.resize((card_w, card_h), Image.LANCZOS)
        canvas.paste(scaled_card, (card_x, card_y), scaled_card)

        # 3b'''. 卡片之上的独立层光效（如 6★光柱）: 盖在卡片上、可溢出卡片框
        self._apply_light_above_card(
            canvas, star_level, base_w, base_h, card_center, zoom)

        # 3b'. 星级标作为独立层绘制在卡片上方(可溢出卡片框,不被卡片裁剪)
        if cfg.STAR_STRIP_OVERFLOW:
            self._draw_star_strip_on_canvas(
                canvas, star_level, card_x, card_y, card_w, card_h, zoom)

        # 3b''. 职业图标作为独立层绘制在卡片底部(可溢出卡片框,不被卡片裁剪)
        if cfg.PROFESSION_ICON_OVERFLOW:
            self._draw_profession_on_canvas(
                canvas, char_name, card_x, card_y, card_w, card_h, zoom)

        return canvas

    # -- 加载缓存好的干员精一立绘（可能为 WEBP/PNG） --
    def _load_elite1_art(self, char_name: str):
        """读取缓存的干员精一立绘，返回 RGBA 图像或 None。

        查找顺序（任一命中即返回）：
          1. 渲染器注入的目录 —— 即当前画质档位目录 elite1_art/<档位>/
          2. cfg.ELITE1_ART_DIR 根目录 —— 兼容历史缓存，以及直接构造 Composer 的场合
          3. 根目录下的各档位子目录 —— 兜底（注入缺失时仍能找到立绘）
        扩展名 png / webp 都尝试（原画质档为 png，压缩档为 webp）。

        结果按干员名做 LRU 缓存：命中时直接返回已解码的图像，跳过磁盘 IO 与
        PNG 解码。注意返回的是【共享对象】，调用方只可读取
        （resize / paste 都不修改原图，现有调用方均满足此约束）。
        """
        cache = self._elite1_art_cache
        cached = cache.get(char_name)
        if cached is not None:
            cache.move_to_end(char_name)
            return cached

        candidates = []
        if self.elite1_art_dir:
            candidates.append(self.elite1_art_dir)
        candidates.append(cfg.ELITE1_ART_DIR)
        try:
            for name in sorted(os.listdir(cfg.ELITE1_ART_DIR)):
                sub = os.path.join(cfg.ELITE1_ART_DIR, name)
                if os.path.isdir(sub) and sub not in candidates:
                    candidates.append(sub)
        except OSError:
            pass

        found = None
        for d in candidates:
            for fn in (f"{char_name}.png", f"{char_name}.webp"):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    try:
                        found = Image.open(p).convert("RGBA")
                    except Exception:
                        continue
                    break
            if found is not None:
                break

        if found is None:
            return None

        cache[char_name] = found
        cache.move_to_end(char_name)
        while len(cache) > self._elite1_art_cache_max:
            cache.popitem(last=False)
        return found

    # =====================================================================
    #  单抽结果图 v3（元素表驱动）
    #    全部构图来自 composer_config.SP3_ELEMENTS / SP3_VIGNETTE，
    #    本类只负责"按层级排序 → 逐个绘制 → 叠加打光"，不含任何硬编码坐标。
    # =====================================================================

    @staticmethod
    def _blank_canvas(width: int, height: int) -> Image.Image:
        """创建空白画布：背景由元素表中的 background 元素负责绘制"""
        base = (0, 0, 0, 255) if cfg.BG_BLACK_BASE else (0, 0, 0, 0)
        return Image.new("RGBA", (width, height), base)

    def _load_sp3_image(self, src: str):
        """
        加载单抽素材（src 可为绝对路径，或素材目录下的文件名），带缓存。
        找不到或解码失败返回 None（不抛异常）。
        """
        if not src:
            return None
        path = src
        if not os.path.isfile(path):
            path = _find_image([src], [cfg.MATERIAL_DIR, cfg.STATE_DIR])
        if not path or not os.path.isfile(path):
            return None
        if path in self._sp3_asset_cache:
            return self._sp3_asset_cache[path]
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            img = None
        self._sp3_asset_cache[path] = img
        return img

    def _sp3_profession_path(self, char_name: str) -> str:
        """带文字职业图标的本地路径（无职业或文件缺失时返回空字符串）"""
        prof = self.get_profession(char_name)
        if not prof:
            return ""
        return os.path.join(cfg.PROFESSION_LABELED_DIR, f"{prof}.png")

    def compose_single_pull_v3(self, result, is_new: bool = False):
        """
        单抽结果图 v3（元素表驱动）。

        绘制顺序：所有启用的元素按 layer【降序】绘制
                  （layer 越大越先画 = 越靠下层），最后叠加打光蒙版。

        result: {"name": str, "rarity": int}
        is_new: 是否为首次获得（True 时才绘制 new_tag）
        返回：合成后的 RGBA 画布
        """
        char_name = (result or {}).get("name", "")
        rarity = int((result or {}).get("rarity", 3) or 3)
        w, h = cfg.SP3_CANVAS

        canvas = self._blank_canvas(w, h)

        # 收集绘制任务：元素可展开为多个实例（随机副本 / 附属 trail），
        # 每个实例可能落在不同层级上，因此先展开再统一排序。
        tasks = []
        for key, elem in cfg.SP3_ELEMENTS.items():
            if elem.get("enabled"):
                tasks.extend(self._expand_sp3_tasks(key, elem))

        # 底部渐变遮罩是独立配置块，但同样用 layer 参与统一排序
        fade = getattr(cfg, "SP3_BOTTOM_FADE", None)
        if fade and fade.get("enabled", False):
            tasks.append(("__bottom_fade__", fade))

        # above_vignette=True 的元素（如 SKIP 按钮等界面元素）在打光【之后】绘制，
        # 避免被画面暗角压暗 —— 它们属于界面层，不应受氛围光影响。
        above = [(k, e) for k, e in tasks if e.get("above_vignette")]
        normal = [(k, e) for k, e in tasks if not e.get("above_vignette")]

        normal.sort(key=lambda ke: ke[1].get("layer", 100), reverse=True)
        for key, el in normal:
            self._draw_sp3_element_safe(canvas, key, el, char_name, rarity, is_new)

        self._apply_vignette(canvas)

        above.sort(key=lambda ke: ke[1].get("layer", 100), reverse=True)
        for key, el in above:
            self._draw_sp3_element_safe(canvas, key, el, char_name, rarity, is_new)

        return canvas

    def _expand_sp3_tasks(self, key, elem):
        """
        把一个元素展开成若干【独立实例】，返回 [(key, 实例字典), ...]。

        · 普通元素 -> 1 个实例（原样返回）。
        · random_count > 0 的元素 -> N 个实例，各自持有自己的随机位置；
          并按概率决定该实例是否旋转 180°（rotate_chance / rotated_layer），
          以及是否附带回装饰（trail，独立实例 + 自己的 layer）。

        这样"翻转后的实例换层级""附属装饰有自己的层级"都能被统一排序正确处理。
        """
        import random

        rc = int(elem.get("random_count", 0) or 0)
        if rc <= 0:
            return [(key, elem)]

        w, h = cfg.SP3_CANVAS
        area = elem.get("random_area", {}) or {}
        rx = area.get("x", (-w / 2.0, w / 2.0))
        ry = area.get("y", (-h / 2.0, h / 2.0))
        base_layer = elem.get("layer", 100)
        rotate_chance = float(elem.get("rotate_chance", 0.0) or 0.0)
        rotated_layer = elem.get("rotated_layer")
        trail = elem.get("trail") or {}

        # 本元素渲染后的实际像素尺寸（用于按比例推算附属 trail 的大小）
        star_img = self._load_sp3_image(elem.get("file", ""))
        star_w, star_h = (0, 0)
        if star_img is not None:
            star_w, star_h = self._resolve_sp3_size(star_img, elem.get("size"))

        # 随机尺寸范围：每个副本各自取一个百分比（未配置则沿用固定的 size）
        random_size = elem.get("random_size")
        # 翻转实例的额外调整：高度偏移 / 独立尺寸 / 着色
        rot_off = elem.get("rotated_offset", (0, 0)) or (0, 0)
        rot_size = elem.get("rotated_size")
        rot_tint = elem.get("rotated_tint")

        tasks = []
        for _ in range(rc):
            px = random.uniform(rx[0], rx[1])
            py = random.uniform(ry[0], ry[1])
            rotated = rotate_chance > 0 and random.random() < rotate_chance
            layer = rotated_layer if (rotated and rotated_layer is not None) else base_layer

            # 尺寸：先按 random_size 随机，翻转实例可再覆盖成 rot_size
            size = elem.get("size")
            if random_size:
                size = random.uniform(min(random_size), max(random_size))
            if rotated:
                px += rot_off[0]
                py += rot_off[1]
                if rot_size is not None:
                    size = rot_size

            inst = dict(elem)
            inst["pos"] = (px, py)
            inst["size"] = size
            inst["layer"] = layer
            inst["_rotated"] = rotated
            if rotated and rot_tint:
                inst["_tint"] = rot_tint
            tasks.append((key, inst))

            # 本实例的实际像素尺寸（trail 按它等比推算）
            if star_img is not None:
                inst_w, inst_h = self._resolve_sp3_size(star_img, size)
            else:
                inst_w, inst_h = star_w, star_h

            # 附属拖尾：作为独立实例，落在自己的层级上，大小按 star 比例推算
            if trail and inst_w > 0:
                if random.random() < float(trail.get("chance", 0.0) or 0.0):
                    ratio = float(trail.get("size_ratio", 1.0))
                    toff = trail.get("offset", (0, 0)) or (0, 0)
                    base_w = max(1, int(inst_w * ratio))
                    base_h = max(1, int(inst_h * ratio))

                    t_elem = {
                        # 支持小数偏移（如 +0.5）：可让 trail 稳定落在所属 star 的
                        # 紧邻下一层，又不会和相邻 star 的整数层撞车。
                        "layer": layer + float(trail.get("layer_offset", -1)),
                        "pos": (px + toff[0], py + toff[1]),
                        "opacity": 1.0,
                        "blend": trail.get("blend", "NORMAL"),
                        "enabled": True,
                        "_rotated": rotated and bool(trail.get("follow_rotate", True)),
                    }

                    if trail.get("type") == "beam":
                        # 程序绘制的柔和光柱（不用素材文件），透明度已烘进图像。
                        # 尺寸：优先取 *_px（绝对像素），未填则用倍率 × star 尺寸。
                        # 注意 beam_width 是【相对 star 宽度的倍数】，填 20 = 20 倍，
                        # 会远超画布导致"柱形被截平"，想精确控制请用 beam_width_px。
                        if trail.get("beam_width_px"):
                            bw = max(1, int(trail["beam_width_px"]))
                        else:
                            bw = max(1, int(base_w * float(trail.get("beam_width", 0.35))))
                        if trail.get("beam_height_px"):
                            bh = max(1, int(trail["beam_height_px"]))
                        else:
                            bh = max(1, int(base_h * float(trail.get("beam_height", 1.8))))
                        # 所属 star 翻转时，光柱默认跟着换成同一个橙色；
                        # 想单独指定可配 trail.rotated_color。
                        beam_color = trail.get("color", (255, 255, 255))
                        if rotated:
                            beam_color = (trail.get("rotated_color")
                                          or elem.get("rotated_tint")
                                          or beam_color)
                        beam = self._make_sp3_beam(
                            bw, bh,
                            beam_color,
                            trail.get("softness_x", 2.2),
                            trail.get("softness_y", 1.0),
                            trail.get("opacity", 0.5),
                            trail.get("flat_ratio", 0.0))
                        if beam is not None:
                            t_elem["_image"] = beam
                            t_elem["size_px"] = (bw, bh)
                            tasks.append((key, t_elem))
                    elif trail.get("file"):
                        t_elem["file"] = trail.get("file")
                        t_elem["size_px"] = (base_w, base_h)
                        t_elem["opacity"] = float(trail.get("opacity", 1.0))
                        tasks.append((key, t_elem))
        return tasks

    def _draw_sp3_element_safe(self, canvas, key, elem, char_name, rarity, is_new):
        """绘制单个元素并吞掉异常，保证一个元素失败不影响整图"""
        try:
            self._draw_sp3_element(canvas, key, elem, char_name, rarity, is_new)
        except Exception as e:
            # 单个元素失败不影响整图，仅打印告警
            print(f"[Composer] 单抽元素 {key} 绘制失败: {e}")

    def _draw_sp3_element(self, canvas, key, elem, char_name, rarity, is_new):
        """按元素类型分派绘制"""
        if key == "background":
            self._draw_sp3_background(canvas, elem)
        elif key == "portrait":
            self._draw_sp3_portrait(canvas, elem, char_name)
        elif key == "camp_logo":
            self._draw_sp3_image(canvas, elem, self.get_camp_logo_path(char_name))
        elif key == "profession":
            self._draw_sp3_image(canvas, elem, self._sp3_profession_path(char_name))
        elif key == "stars":
            self._draw_sp3_stars(canvas, elem, rarity)
        elif key == "new_tag":
            if is_new:
                self._draw_sp3_image(canvas, elem, elem.get("file", ""))
        elif key in ("name_cn", "name_en"):
            self._draw_sp3_text(canvas, elem, char_name)
        elif key == "__bottom_fade__":
            self._draw_sp3_bottom_fade(canvas, elem)
        else:
            # 其余（deco_* 等）按普通图片元素处理
            self._draw_sp3_image(canvas, elem, elem.get("file", ""))

    def _draw_sp3_background(self, canvas, elem):
        """
        绘制背景：铺满画布，应用 POT 裁剪与全局亮度。

        单抽使用独立背景（SP3_BACKGROUND_FILE = 十连背景的局部放大版），
        与十连的 background 元素互不影响。
        """
        bg = self._load_sp3_image(elem.get("file", ""))
        if bg is None:
            return
        w, h = canvas.size
        bg = bg.copy()
        bg = _prepare_background(bg)
        if bg.size != (w, h):
            bg = bg.resize((w, h), Image.LANCZOS)
        if cfg.BG_BRIGHTNESS != 1.0:
            bg = ImageEnhance.Brightness(bg).enhance(cfg.BG_BRIGHTNESS)

        opacity = float(elem.get("opacity", 1.0))
        if opacity < 1.0:
            a = bg.getchannel("A").point(lambda v: int(v * max(0.0, opacity)))
            bg.putalpha(a)

        px, py = elem.get("pos", (0, 0))
        canvas.paste(bg, (int(px), int(py)), bg)

    def _draw_sp3_portrait(self, canvas, elem, char_name):
        """绘制精一立绘：高度 = 画布高 × fill × size_percent/100，以 pos 为中心"""
        art = self._load_elite1_art(char_name)
        if art is None:
            return
        w, h = canvas.size
        fill = float(elem.get("fill", 1.0))
        pct = float(elem.get("size_percent", 100))
        target_h = max(1, int(h * fill * pct / 100.0))
        target_w = max(1, int(round(art.width * (target_h / max(1, art.height)))))
        art = art.resize((target_w, target_h), Image.LANCZOS)

        px, py = elem.get("pos", (0, 0))
        x = int(w / 2.0 + px - target_w / 2.0)
        y = int(h / 2.0 + py - target_h / 2.0)
        canvas.paste(art, (x, y), art)

    @staticmethod
    def _resolve_sp3_size(img, size):
        """
        把元素配置的 size 解析为目标像素宽高。

        size 语义为【百分比等比缩放】：
          · None / 100      -> 素材原始尺寸
          · 数字，如 50/150 -> 宽高同时按该百分比缩放（保持宽高比，不会压扁）
          · (w_pct, h_pct)  -> 宽、高分别按百分比缩放（非等比，仅特殊需求时使用）
        """
        iw, ih = img.size
        if size is None:
            return max(1, iw), max(1, ih)
        if isinstance(size, (int, float)):
            s = float(size) / 100.0
            return max(1, int(round(iw * s))), max(1, int(round(ih * s)))
        try:
            sw = float(size[0]) / 100.0
            sh = float(size[1]) / 100.0
        except (TypeError, IndexError, ValueError):
            return max(1, iw), max(1, ih)
        return max(1, int(round(iw * sw))), max(1, int(round(ih * sh)))

    def _make_sp3_beam(self, w, h, color, softness_x, softness_y, opacity,
                       flat_ratio=0.0):
        """
        程序生成一根【柔和光柱】（RGBA），用于替代"四束拼接"的素材拖尾。

        形状：横向中心最亮、向两侧平滑衰减；纵向两端同样淡出。
        参数：
          w, h        : 光柱像素尺寸
          color       : 光柱颜色
          softness_x  : 横向衰减指数，越大越柔越淡（"淡"就调大）
          softness_y  : 纵向衰减指数
          opacity     : 整体不透明度 0~1（"淡"就调小）
          flat_ratio  : 横向【平顶】比例 0~0.9。中心这一段保持全亮，
                        只有外侧 (1-flat_ratio) 羽化。
                        0   = 纯锥形（仅中心一点最亮，加宽也只是把雾摊开，看着仍像细线）
                        0.5 = 中心一半宽度是实的 —— 参考图那种"粗条状光柱"
        结果按参数缓存，避免逐实例重复计算。
        """
        key = (int(w), int(h), tuple(color), float(softness_x),
               float(softness_y), float(opacity), float(flat_ratio))
        cached = self._sp3_beam_cache.get(key)
        if cached is not None:
            return cached

        try:
            import numpy as np
        except ImportError:
            return None

        w, h = max(1, int(w)), max(1, int(h))
        ys, xs = np.indices((h, w)).astype(np.float32)

        # 横向：中心(0) -> 边缘(1)
        dx = np.abs(xs - (w - 1) / 2.0) / max((w - 1) / 2.0, 1e-6)
        flat = min(max(float(flat_ratio), 0.0), 0.9)
        if flat > 1e-6:
            # 平顶：dx <= flat 的范围内恒为全亮，只有外侧按 softness_x 羽化收束
            edge = np.clip((1.0 - dx) / (1.0 - flat), 0.0, 1.0)
            ax = np.where(dx <= flat, 1.0,
                          edge ** max(float(softness_x), 1e-6))
        else:
            ax = np.clip(1.0 - dx, 0.0, 1.0) ** max(float(softness_x), 1e-6)

        # 纵向：中心(0) -> 两端(1)
        dy = np.abs(ys - (h - 1) / 2.0) / max((h - 1) / 2.0, 1e-6)
        ay = np.clip(1.0 - dy, 0.0, 1.0) ** max(float(softness_y), 1e-6)

        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[:, :, 0] = color[0]
        arr[:, :, 1] = color[1]
        arr[:, :, 2] = color[2]
        arr[:, :, 3] = np.clip(ax * ay * float(opacity) * 255.0, 0, 255).astype(np.uint8)

        img = Image.fromarray(arr, "RGBA")
        self._sp3_beam_cache[key] = img
        return img

    def _draw_sp3_backdrop(self, canvas, elem):
        """
        绘制元素的可选【底板】（纯色圆角矩形）。

        用于还原 SKIP 按钮这类"灰黑底 + 亮色内容"的界面元素：
        素材本身只有白色文字/图形，底板由这里程序生成。

        配置（挂在元素下，随元素一起绘制、共享 above_vignette 等设置）：
          "backdrop": {
              "enabled": True,
              "color":  (28, 30, 34, 210),  # RGBA，前三个是灰黑，alpha 控制虚实
              "size":   (120, 62),          # 底板宽高（像素，与素材缩放无关）
              "radius": 6,                  # 圆角半径，0 = 直角
              "offset": (0, 0),             # 相对【元素中心】的偏移
          }
        仅对固定位置的元素有效（启用 random_count 的元素不适用）。
        """
        bd = elem.get("backdrop")
        if not bd or not bd.get("enabled", True):
            return

        w, h = canvas.size
        try:
            bw, bh = bd.get("size", (120, 60))
            bw, bh = max(1, int(bw)), max(1, int(bh))
        except (TypeError, ValueError):
            return
        radius = max(0, int(bd.get("radius", 0) or 0))
        color = tuple(bd.get("color", (28, 30, 34, 200)))
        ox, oy = bd.get("offset", (0, 0)) or (0, 0)
        px, py = elem.get("pos", (0, 0))

        cx = w / 2.0 + px + ox
        cy = h / 2.0 + py + oy
        x = int(cx - bw / 2.0)
        y = int(cy - bh / 2.0)

        layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        if radius > 0:
            draw.rounded_rectangle([0, 0, bw - 1, bh - 1],
                                   radius=radius, fill=color)
        else:
            draw.rectangle([0, 0, bw - 1, bh - 1], fill=color)
        canvas.paste(layer, (x, y), layer)

    def _draw_sp3_image(self, canvas, elem, src):
        """
        绘制普通图片元素（单个实例）。

        · size 为百分比等比缩放；size_px 为直接指定像素尺寸（优先于 size）。
        · pos 为元素中心相对画布中心的偏移。
        · _rotated=True 时整体旋转 180°（翻转）。
        · 若配置了 backdrop，会先在元素位置画一层纯色圆角矩形底板。
        注：随机副本（含旋转与附属 trail）已在 _expand_sp3_tasks 阶段展开为多个实例。
        """
        # 底板先画（垫在图片下方）
        self._draw_sp3_backdrop(canvas, elem)

        # _image：程序生成的图像（如光柱），优先于素材文件
        img = elem.get("_image")
        if img is None:
            img = self._load_sp3_image(src)
        if img is None:
            return

        if elem.get("size_px"):
            try:
                tw = max(1, int(elem["size_px"][0]))
                th = max(1, int(elem["size_px"][1]))
            except (TypeError, IndexError, ValueError):
                tw, th = self._resolve_sp3_size(img, elem.get("size"))
        else:
            tw, th = self._resolve_sp3_size(img, elem.get("size"))
        if (tw, th) != img.size:
            img = img.resize((tw, th), Image.LANCZOS)

        # 翻转（旋转 180°，尺寸不变）
        if elem.get("_rotated"):
            img = img.rotate(180)

        # 着色（如翻转后的装饰星染成暖橙色），在缩放/翻转之后进行
        tint = elem.get("_tint")
        if tint:
            img = _tint_image(img, tint,
                              float(elem.get("_tint_strength", 1.0)))

        opacity = float(elem.get("opacity", 1.0))
        blend = elem.get("blend", "NORMAL")
        px, py = elem.get("pos", (0, 0))
        self._paste_sp3_image(canvas, img, tw, th, px, py, opacity, blend)

    @staticmethod
    def _paste_sp3_image(canvas, img, tw, th, offset_x, offset_y, opacity, blend):
        """按【中心相对画布中心的偏移】把已缩放的图片贴到画布上"""
        w, h = canvas.size
        x = int(w / 2.0 + offset_x - tw / 2.0)
        y = int(h / 2.0 + offset_y - th / 2.0)
        if opacity >= 1.0 and blend == "NORMAL":
            canvas.paste(img, (x, y), img)
        else:
            tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            tmp.paste(img, (x, y), img)
            _blend_onto(canvas, tmp, opacity, blend)

    def _draw_sp3_stars(self, canvas, elem, rarity):
        """
        绘制星级五角星：数量取干员星级，横向排列。

        size 与其它元素统一，为【百分比等比缩放】（None/100 = 素材原始尺寸）；
        gap 为相邻两颗之间的像素间距。
        """
        img = self._load_sp3_image(elem.get("file", ""))
        if img is None:
            return

        if elem.get("count_from_rarity", True):
            count = int(rarity)
        else:
            count = int(elem.get("fixed_count", 6))
        count = max(1, count)

        star_w, star_h = self._resolve_sp3_size(img, elem.get("size"))
        gap = int(elem.get("gap", 6))
        align = elem.get("align", "center")

        w, h = canvas.size
        px, py = elem.get("pos", (0, 0))
        total_w = count * star_w + (count - 1) * gap
        cx = w / 2.0 + px
        cy = h / 2.0 + py

        if align == "center":
            x0 = cx - total_w / 2.0
        elif align == "right":
            x0 = cx - total_w
        else:
            x0 = cx

        star = img if (star_w, star_h) == img.size else \
            img.resize((star_w, star_h), Image.LANCZOS)
        opacity = float(elem.get("opacity", 1.0))
        if opacity < 1.0:
            star = star.copy()
            a = star.getchannel("A").point(lambda v: int(v * max(0.0, opacity)))
            star.putalpha(a)

        x = x0
        for _ in range(count):
            canvas.paste(star, (int(x), int(cy - star_h / 2.0)), star)
            x += star_w + gap

    def _draw_sp3_text(self, canvas, elem, char_name):
        """绘制干员中文名/英文名（白填充 + 黑外描边），以 pos 为文字块中心"""
        src = elem.get("text", "cn")
        text = self.get_en_name(char_name) if src == "en" else char_name
        if not text:
            return
        if elem.get("uppercase"):
            text = text.upper()

        size = max(1, int(elem.get("font_size", 32)))
        weight = int(elem.get("weight", 700))
        ls = float(elem.get("letter_spacing", 0.0))
        font_file = elem.get("font", "")

        total_w, ascent, descent = text_render.measure_text(
            text, size, weight, ls, font_file)
        if total_w <= 0:
            return

        w, h = canvas.size
        px, py = elem.get("pos", (0, 0))
        cx = w / 2.0 + px
        cy = h / 2.0 + py
        # 让文字视觉垂直居中：基线在中心下方 (ascent - descent)/2
        baseline_y = cy + (ascent - descent) / 2.0

        text_render.draw_outlined_text(
            canvas, (cx, baseline_y), text,
            size=size, weight=weight,
            fill=tuple(elem.get("fill", (255, 255, 255, 255))),
            stroke_fill=tuple(elem.get("stroke_fill", (128, 128, 128, 255))),
            stroke_width=int(elem.get("stroke_width", 0)),
            letter_spacing_ratio=ls,
            halign=elem.get("align", "center"),
            opacity=float(elem.get("opacity", 1.0)),
            font_file=font_file,
            color_mode=bool(elem.get("color_mode", False)),
        )

    def _draw_sp3_bottom_fade(self, canvas, elem):
        """
        底部渐变遮罩（三段式，自下而上）：
          · [solid_height] 纯色段，alpha 恒为 max_alpha（完全不透明）
          · [fade_height ] 渐变段，alpha 由 max_alpha 渐隐到 0
          · 其余部分       全透明

        总覆盖高度 = solid_height + fade_height，两段独立可控。
        由 composer_config.SP3_BOTTOM_FADE 驱动；layer 通过元素表排序决定绘制时机。
        """
        w, h = canvas.size
        color = tuple(elem.get("color", (0, 0, 0)))
        max_alpha = float(elem.get("max_alpha", 255))
        power = max(1e-6, float(elem.get("power", 1.0)))
        ox, oy = elem.get("pos", (0, 0))

        # 兼容旧参数：若没有 fade_height，则把 height 当作渐变段高度
        if "fade_height" in elem:
            solid_h = max(0, int(elem.get("solid_height", 0)))
            fade_h = max(0, int(elem.get("fade_height", 0)))
        else:
            solid_h = 0
            fade_h = max(0, int(elem.get("height", 160)))

        if solid_h <= 0 and fade_h <= 0:
            return

        base_y = h + int(oy)          # 底部基准（pos.y 为负则整体上移）
        solid_top = base_y - solid_h  # 纯色段顶端
        fade_top = solid_top - fade_h  # 渐变段顶端（此线以上全透明）

        try:
            import numpy as np
        except ImportError:
            return

        ys = np.arange(h, dtype=np.float32)
        alpha = np.zeros(h, dtype=np.float32)

        # 渐变段：fade_top(alpha=0) -> solid_top(alpha=max)
        if fade_h > 0:
            t = np.clip((ys - fade_top) / float(fade_h), 0.0, 1.0) ** power
            alpha = t * max_alpha
        # 纯色段：solid_top 以下恒为 max_alpha
        alpha = np.where(ys >= solid_top, max_alpha, alpha)
        # 渐变段以上强制全透明
        alpha = np.where(ys < fade_top, 0.0, alpha)
        alpha = np.clip(alpha, 0, 255).astype(np.uint8)

        layer = np.zeros((h, w, 4), dtype=np.uint8)
        layer[:, :, 0] = color[0]
        layer[:, :, 1] = color[1]
        layer[:, :, 2] = color[2]
        layer[:, :, 3] = alpha[:, None]

        fade_img = Image.fromarray(layer, "RGBA")
        if ox:
            # 水平偏移：整体平移，空出的部分保持透明
            shifted = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            shifted.paste(fade_img, (int(ox), 0), fade_img)
            fade_img = shifted
        canvas.alpha_composite(fade_img)

    def _apply_vignette(self, canvas):
        """
        叠加椭圆暗角打光：椭圆内部不压暗，向外按羽化曲线渐变到最暗。
        由 composer_config.SP3_VIGNETTE 驱动，最后一步应用。
        """
        v = getattr(cfg, "SP3_VIGNETTE", None)
        if not v or not v.get("enabled", False):
            return

        w, h = canvas.size
        ox, oy = v.get("center", (0, 0))
        cx = w / 2.0 + float(ox)
        cy = h / 2.0 + float(oy)
        vw, vh = v.get("size", (w, h))
        rw = max(1.0, float(vw) / 2.0)
        rh = max(1.0, float(vh) / 2.0)
        feather = max(1e-6, float(v.get("feather", 0.35)))
        darkness = float(v.get("darkness", 0.75))
        power = float(v.get("power", 1.0))
        color = tuple(v.get("color", (0, 0, 0)))
        invert = bool(v.get("invert", False))

        try:
            import numpy as np
        except ImportError:
            return

        ys, xs = np.indices((h, w)).astype(np.float32)
        # 归一化椭圆距离：0 = 中心，1 = 椭圆边界
        d = np.sqrt(((xs - cx) / rw) ** 2 + ((ys - cy) / rh) ** 2)
        inner = max(0.0, 1.0 - feather)
        t = np.clip((d - inner) / feather, 0.0, 1.0) ** max(power, 1e-6)
        if invert:
            t = 1.0 - t

        layer = np.zeros((h, w, 4), dtype=np.uint8)
        layer[:, :, 0] = color[0]
        layer[:, :, 1] = color[1]
        layer[:, :, 2] = color[2]
        layer[:, :, 3] = np.clip(t * darkness * 255.0, 0, 255).astype(np.uint8)

        canvas.alpha_composite(Image.fromarray(layer, "RGBA"))

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
