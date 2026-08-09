"""
image_renderer.py - 明日方舟抽卡结果图片渲染器（接入 Generator_test 合成逻辑）

图片合成逻辑（构图参数、光效布局、程序生成光晕/小亮条/星点着色等）已 100% 复刻
自 Generator_test 的 image_composer.py + composer_config.py。
本文件保留 ImageRenderer 对外接口（render_ten_pull / render_single_pull）与
半身像/职业图标动态下载缓存逻辑，内部改为调用 image_composer.Composer 完成合成。

用法:
  renderer = ImageRenderer(plugin_dir)
  path = await renderer.render_ten_pull(results, pool_name)
  path = await renderer.render_single_pull(result, pool_name)
"""

import asyncio
import hashlib
import json
import os
import time
from typing import List, Optional
from urllib.parse import quote

from PIL import Image

import image_composer as _composer
from image_composer import Composer


# ──────────────────── 常量 ────────────────────

# 十连画布尺寸（与 composer_config 一致）
CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 576

# PRTS 媒体 URL 基地址
PRTS_MEDIA_BASE = "https://media.prts.wiki"

# 抽卡结果图保留时长（秒）。结果图 100% 不会被复用，仅短暂保留供发送，
# 超过此时间后在下一次渲染时自动清理，避免 gacha_results 目录无限膨胀。
GACHA_RESULT_TTL = 3600  # 1 小时


# ──────────────────── 工具函数 ────────────────────

def _md5_url(filename: str) -> str:
    """根据 PRTS Wiki 的 MD5 规则构造媒体文件 URL"""
    md5_hex = hashlib.md5(filename.encode("utf-8")).hexdigest()
    return f"{PRTS_MEDIA_BASE}/{md5_hex[0]}/{md5_hex[:2]}/{quote(filename, safe='')}"


def _load_image_safe(path: str) -> Optional[Image.Image]:
    """安全加载图片，失败返回 None"""
    try:
        if os.path.isfile(path):
            return Image.open(path).convert("RGBA")
    except Exception:
        pass
    return None


# ──────────────────── ImageRenderer ────────────────────

class ImageRenderer:
    """抽卡结果图片渲染器"""

    def __init__(self, plugin_dir: str):
        """
        plugin_dir: 插件根目录路径
        """
        self.plugin_dir = plugin_dir
        self.cache_dir = os.path.join(plugin_dir, "data", "cache")
        self.portrait_dir = os.path.join(self.cache_dir, "portraits")
        self.profession_dir = os.path.join(self.cache_dir, "professions")
        self.output_dir = os.path.join(self.cache_dir, "gacha_results")

        # 职业映射表 {干员名: 职业中文名}（由合成器加载，此处仅为兼容保留）
        self.profession_map: dict = {}

        # 合成器（懒加载）
        self._composer: Optional[Composer] = None

        self._loaded = False
        self._lock = asyncio.Lock()

    # ──────────────────── 初始化 ────────────────────

    def _ensure_dirs(self):
        """创建缓存目录"""
        for d in [self.cache_dir, self.portrait_dir, self.profession_dir, self.output_dir]:
            os.makedirs(d, exist_ok=True)

    def _cleanup_output_dir(self):
        """
        清理过期的抽卡结果图。

        结果图 100% 不会被复用（每次抽卡都生成全新图片），只短暂保留以便发送。
        每次渲染前调用，删除超过 GACHA_RESULT_TTL 秒的旧文件，防止目录无限膨胀。
        """
        try:
            if not os.path.isdir(self.output_dir):
                return
            now = time.time()
            cutoff = now - GACHA_RESULT_TTL
            for fname in os.listdir(self.output_dir):
                if not fname.lower().endswith(".png"):
                    continue
                path = os.path.join(self.output_dir, fname)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    continue
        except Exception:
            # 清理失败不应影响本次渲染
            pass

    def _get_composer(self) -> Composer:
        """懒加载并返回合成器"""
        if self._composer is None:
            self._composer = Composer()
            # 同步职业映射到本类，供下载逻辑使用
            self.profession_map = dict(getattr(self._composer, "_professions_map", {}))
        return self._composer

    async def initialize(self):
        """异步初始化：创建目录 + 加载合成器（含全部素材）"""
        async with self._lock:
            self._ensure_dirs()
            self._get_composer()
            self._loaded = True

    # ──────────────────── 半身像 / 职业图标下载 ────────────────────

    def _get_portrait_url(self, char_name: str) -> str:
        """构造干员半身像的 PRTS URL"""
        filename = f"半身像_{char_name}_1.png"
        return _md5_url(filename)

    def _get_profession_url(self, profession: str) -> str:
        """构造职业图标的 PRTS URL"""
        filename = f"图标_职业_{profession}_大图_白.png"
        return _md5_url(filename)

    def _get_portrait_path(self, char_name: str) -> str:
        return os.path.join(self.portrait_dir, f"{char_name}.png")

    def _get_profession_path(self, profession: str) -> str:
        return os.path.join(self.profession_dir, f"{profession}.png")

    async def _download_image(self, url: str, save_path: str) -> bool:
        """下载图片到本地，返回是否成功"""
        if os.path.isfile(save_path):
            return True

        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        # 验证是有效图片
                        try:
                            from io import BytesIO
                            img = Image.open(BytesIO(data))
                            img.verify()
                        except Exception:
                            return False
                        with open(save_path, "wb") as f:
                            f.write(data)
                        return True
        except Exception:
            pass
        return False

    async def _ensure_portrait(self, char_name: str) -> Optional[str]:
        """确保半身像已缓存，返回本地路径或 None"""
        local_path = self._get_portrait_path(char_name)
        if os.path.isfile(local_path):
            return local_path

        url = self._get_portrait_url(char_name)
        ok = await self._download_image(url, local_path)
        return local_path if ok else None

    async def _ensure_profession_icon(self, profession: str) -> Optional[str]:
        """确保职业图标已缓存，返回本地路径或 None"""
        local_path = self._get_profession_path(profession)
        if os.path.isfile(local_path):
            return local_path

        url = self._get_profession_url(profession)
        ok = await self._download_image(url, local_path)
        return local_path if ok else None

    async def _ensure_all_images(self, results: List[dict]):
        """并发下载十连中所有需要的半身像和职业图标"""
        tasks = []
        for r in results:
            name = r["name"]
            tasks.append(self._ensure_portrait(name))

            profession = self.profession_map.get(name, "")
            if profession:
                tasks.append(self._ensure_profession_icon(profession))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ──────────────────── 公开接口 ────────────────────

    async def render_ten_pull(
        self, results: List[dict], pool_name: str = "",
    ) -> Optional[str]:
        """
        渲染十连结果图片。

        results: [{"name": str, "rarity": int, "is_up": bool}, ...] (10 个)
        pool_name: 卡池名（用于文件名）

        返回输出图片的本地路径，失败返回 None。
        """
        if not self._loaded:
            await self.initialize()

        # 清理过期的历史结果图，防止目录无限膨胀
        self._cleanup_output_dir()

        # 确保所有图片已缓存
        await self._ensure_all_images(results)

        # 合成十连图（完整复用 Generator_test 逻辑）
        composer = self._get_composer()
        final = composer.compose_ten_pull(results)

        # 保存：转 RGB 丢弃 alpha，确保输出完全不透明
        ts = int(time.time() * 1000)
        safe_name = pool_name.replace("/", "_").replace("\\", "_")[:30] if pool_name else "draw"
        filename = f"tenpull_{safe_name}_{ts}.png"
        out_path = os.path.join(self.output_dir, filename)
        final.convert("RGB").save(out_path, "PNG")
        return out_path

    async def render_single_pull(
        self, result: dict, pool_name: str = "",
    ) -> Optional[str]:
        """
        渲染单抽结果图片。

        result: {"name": str, "rarity": int, "is_up": bool}
        """
        if not self._loaded:
            await self.initialize()

        # 清理过期的历史结果图，防止目录无限膨胀
        self._cleanup_output_dir()

        # 确保图片已缓存
        await self._ensure_all_images([result])

        # 用合成器生成单张角色卡片
        composer = self._get_composer()
        card = composer._composite_card(
            char_name=result["name"],
            rarity=result["rarity"],
        )

        if card is None:
            return None

        # 创建单抽画布：最底层先铺纯黑不透明实底，避免背景素材透明区域透过
        canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 255))

        # 背景（裁剪 POT 填充黑边后直接使用，不 resize）
        if composer._bg:
            bg = composer._bg.copy()
            bg = _composer._prepare_background(bg)
            canvas = Image.alpha_composite(canvas, bg)

        # 卡片居中放大（适配单抽画布）
        cw, ch = card.size
        scale = min((CANVAS_WIDTH * 0.88) / cw, (CANVAS_HEIGHT * 0.92) / ch)
        new_w = int(cw * scale)
        new_h = int(ch * scale)
        scaled_card = card.resize((new_w, new_h), Image.LANCZOS)

        px = (CANVAS_WIDTH - new_w) // 2
        py = (CANVAS_HEIGHT - new_h) // 2
        canvas.paste(scaled_card, (px, py), scaled_card)

        # 保存：转 RGB 丢弃 alpha，确保输出完全不透明
        ts = int(time.time() * 1000)
        safe_name = pool_name.replace("/", "_").replace("\\", "_")[:30] if pool_name else "draw"
        filename = f"single_{safe_name}_{ts}.png"
        out_path = os.path.join(self.output_dir, filename)
        canvas.convert("RGB").save(out_path, "PNG")
        return out_path
