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

from astrbot.api import logger

import composer_config as cfg
from image_composer import Composer, profession_map_path


# ──────────────────── 常量 ────────────────────

# PRTS 媒体 URL 基地址
PRTS_MEDIA_BASE = "https://media.prts.wiki"

# 抽卡结果图保留时长（秒）。结果图 100% 不会被复用，仅短暂保留供发送，
# 超过此时间后在下一次渲染时自动清理，避免 gacha_results 目录无限膨胀。
GACHA_RESULT_TTL = 3600  # 1 小时

# 职业图标（带文字版）的兜底职业列表。
# 仅在职业映射（characters_raw.json）尚未就绪时使用，避免首次运行漏拉。
FALLBACK_PROFESSIONS = (
    "先锋", "近卫", "狙击", "重装", "医疗", "辅助", "术师", "特种",
)


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

    def __init__(self, plugin_dir: str, portrait_quality: str = ""):
        """
        plugin_dir:       插件根目录路径
        portrait_quality: 立绘缓存画质档位（对应 AstrBot 配置项 portrait_cache_quality）。
                          留空或非法值时回退到 composer_config.DEFAULT_PORTRAIT_QUALITY。
        """
        self.plugin_dir = plugin_dir
        # 缓存统一放在框架分配的插件专属数据目录下（见 composer_config.DATA_DIR）
        self.cache_dir = cfg.CACHE_DIR
        self.portrait_dir = os.path.join(self.cache_dir, "portraits")
        self.profession_dir = os.path.join(self.cache_dir, "professions")
        # 带文字的职业图标（单抽用）。与无文字版分开存放，互不影响。
        self.profession_labeled_dir = os.path.join(
            self.cache_dir, "professions_labeled")
        self.elite1_art_dir = os.path.join(self.cache_dir, "elite1_art")
        self.output_dir = os.path.join(self.cache_dir, "gacha_results")

        # 立绘缓存画质档位：决定缓存子目录、是否降采样、以及压缩格式与画质
        presets = getattr(cfg, "PORTRAIT_QUALITY_PRESETS", {}) or {}
        default_q = getattr(cfg, "DEFAULT_PORTRAIT_QUALITY", "original")
        self.portrait_quality = str(portrait_quality or "").strip().lower()
        if self.portrait_quality not in presets:
            self.portrait_quality = (default_q if default_q in presets
                                     else next(iter(presets), "original"))
        self._art_preset = presets.get(self.portrait_quality) or {
            "max_height": 0, "format": "PNG", "quality": 100}

        # 职业映射表 {干员名: 职业中文名}（由合成器加载，此处仅为兼容保留）
        self.profession_map: dict = {}

        # 合成器（懒加载）
        self._composer: Optional[Composer] = None

        # 上次加载职业映射时 characters_raw.json 的修改时间（用于检测数据是否已更新）
        self._professions_mtime: float = 0.0

        self._loaded = False
        self._lock = asyncio.Lock()

    # ──────────────────── 初始化 ────────────────────

    def _ensure_dirs(self):
        """创建缓存目录；并做一次历史目录迁移（e2_art → elite1_art）"""
        # 一次性迁移：旧目录名 e2_art 里实际存的是【精一立绘】，已重命名为 elite1_art。
        # 仅在旧目录存在且新目录不存在时迁移，避免覆盖已有缓存。
        old_dir = os.path.join(self.cache_dir, "e2_art")
        if os.path.isdir(old_dir) and not os.path.isdir(self.elite1_art_dir):
            try:
                os.rename(old_dir, self.elite1_art_dir)
                logger.info("[ArkGacha] 已迁移立绘缓存目录 e2_art → elite1_art")
            except OSError as e:
                logger.warning(f"[ArkGacha] 立绘缓存目录迁移失败（忽略）: {e}")

        for d in [self.cache_dir, self.portrait_dir, self.profession_dir,
                  self.profession_labeled_dir, self.elite1_art_dir,
                  self._elite1_art_quality_dir(), self.output_dir]:
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
            self._professions_mtime = self._raw_mtime()
        return self._composer

    def _raw_mtime(self) -> float:
        """characters_raw.json 的最后修改时间（文件不存在时返回 0.0）"""
        try:
            return os.path.getmtime(profession_map_path())
        except OSError:
            return 0.0

    def reload_professions(self) -> int:
        """
        重新加载 干员名 -> 职业 映射，返回映射条目数。

        干员数据更新（characters_raw.json 变化）后调用，使新干员的职业图标
        立即生效，无需热重载插件。
        """
        composer = self._get_composer()
        reload_fn = getattr(composer, "reload_profession_map", None)
        if callable(reload_fn):
            reload_fn()
        self.profession_map = dict(getattr(composer, "_professions_map", {}))
        self._professions_mtime = self._raw_mtime()
        return len(self.profession_map)

    def _refresh_professions_if_stale(self) -> bool:
        """
        若 characters_raw.json 比上次加载更新，则重载职业映射。
        返回是否发生了重载。
        """
        self._get_composer()  # 确保合成器与职业映射已就绪
        if self._raw_mtime() != self._professions_mtime:
            count = self.reload_professions()
            logger.info(f"[ArkGacha] 检测到干员数据更新，已重载职业映射（{count} 条）")
            return True
        return False

    async def initialize(self):
        """异步初始化：创建目录 + 加载合成器（含全部素材）"""
        async with self._lock:
            self._ensure_dirs()
            self._get_composer()
            # 一次性预拉取带文字职业图标（失败仅告警，不阻断初始化）
            await self._prefetch_profession_labeled()
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

    def _get_profession_labeled_url(self, profession: str) -> str:
        """
        构造【带文字】职业图标的 PRTS URL。

        文件名形如 `图标_职业_先锋_带文字.png`（左侧图标 + 右侧职业名），
        与无文字版 `_大图_白` 是两个不同文件，互不影响。
        已实测：八大职业该文件在 PRTS 上均存在。
        """
        filename = f"图标_职业_{profession}_带文字.png"
        return _md5_url(filename)

    def _get_elite1_art_urls(self, char_name: str) -> List[str]:
        """
        构造干员立绘的 PRTS URL 候选列表（按优先级排列）。

        统一使用【精英1立绘】(立绘_<干员名>_1.png)，使 3/4/5/6★ 各星级的立绘
        风格保持一致（3★ 本身就没有精英2立绘，此前混用精二会导致风格不统一）。
        仅当极少数干员缺少精一立绘时，才兜底到精英2立绘。
        """
        return [
            _md5_url(f"立绘_{char_name}_1.png"),   # 精英1立绘（统一使用）
            _md5_url(f"立绘_{char_name}_2.png"),   # 精英2立绘（极端情况兜底）
        ]

    def _get_portrait_path(self, char_name: str) -> str:
        return os.path.join(self.portrait_dir, f"{char_name}.png")

    def _get_profession_path(self, profession: str) -> str:
        return os.path.join(self.profession_dir, f"{profession}.png")

    def _get_profession_labeled_path(self, profession: str) -> str:
        return os.path.join(self.profession_labeled_dir, f"{profession}.png")

    def _elite1_art_quality_dir(self) -> str:
        """当前画质档位对应的缓存子目录（切换档位即换目录，互不覆盖）"""
        return os.path.join(self.elite1_art_dir, self.portrait_quality)

    def _elite1_art_ext(self) -> str:
        fmt = str(self._art_preset.get("format", "PNG")).upper()
        return "webp" if fmt == "WEBP" else "png"

    def _get_elite1_art_path(self, char_name: str) -> str:
        return os.path.join(self._elite1_art_quality_dir(),
                            f"{char_name}.{self._elite1_art_ext()}")

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

    async def _ensure_profession_labeled_icon(self, profession: str) -> Optional[str]:
        """
        确保【带文字】职业图标已缓存，返回本地路径或 None（首次需求时拉取）。

        下载后永久保留（本目录不参与任何 TTL 清理）；配合 _download_image
        内建的"已存在则直接返回"逻辑，天然幂等，重复调用不产生额外请求。
        """
        local_path = self._get_profession_labeled_path(profession)
        if os.path.isfile(local_path):
            return local_path

        url = self._get_profession_labeled_url(profession)
        ok = await self._download_image(url, local_path)
        return local_path if ok else None

    def _profession_list(self) -> List[str]:
        """
        取需要拉取带文字图标的职业列表。

        优先从职业映射（characters_raw.json）动态汇总，未来新增职业可自动覆盖；
        映射尚未就绪（首次运行 / 数据未更新）时回退到八大职业兜底列表。
        """
        professions = {v for v in self.profession_map.values() if v}
        if not professions:
            professions = set(FALLBACK_PROFESSIONS)
        return sorted(professions)

    async def _prefetch_profession_labeled(self) -> int:
        """
        一次性预拉取全部带文字职业图标，返回成功数。

        设计约束：
          · 整体不抛异常 —— 网络不可用时仅告警，绝不能阻断插件初始化；
          · 已存在的文件会被 _download_image 直接跳过，重复启动几乎零开销；
          · 并发拉取，单个职业失败不影响其它职业。
        """
        try:
            professions = self._profession_list()
            if not professions:
                return 0
            results = await asyncio.gather(
                *(self._ensure_profession_labeled_icon(p) for p in professions),
                return_exceptions=True,
            )
            ok = sum(1 for r in results if isinstance(r, str) and r)
            logger.info(
                f"[ArkGacha] 带文字职业图标预拉取完成 {ok}/{len(professions)}")
            return ok
        except Exception as e:
            logger.warning(
                f"[ArkGacha] 带文字职业图标预拉取失败（不影响使用）: {e}")
            return 0

    async def _fetch_bytes(self, url: str) -> Optional[bytes]:
        """下载原始字节（超时可调，用于干员立绘这类大文件），失败返回 None"""
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception:
            pass
        return None

    async def _ensure_elite1_art(self, char_name: str) -> Optional[str]:
        """
        确保干员立绘已缓存，返回本地路径或 None。

        立绘候选按优先级依次尝试（见 _get_elite1_art_urls）：统一使用精英1立绘，
        缺少精一立绘时兜底到精英2立绘，保证单抽图始终有立绘可画。

        原图 1024~2560px、0.7~5.3MB。是否降采样、压缩格式与画质由
        AstrBot 配置项 portrait_cache_quality 对应的档位决定
        （默认 original = 原画质，不做任何降采样）。
        """
        # 命中【当前档位】的缓存直接返回；同档位内兼容 .webp / .png 两种扩展名
        quality_dir = self._elite1_art_quality_dir()
        for fn in (f"{char_name}.{self._elite1_art_ext()}", f"{char_name}.webp",
                   f"{char_name}.png"):
            p = os.path.join(quality_dir, fn)
            if os.path.isfile(p):
                return p

        local_path = self._get_elite1_art_path(char_name)
        data = None
        for url in self._get_elite1_art_urls(char_name):
            data = await self._fetch_bytes(url)
            if data:
                break
        if not data:
            logger.warning(f"[ArkGacha] 干员立绘下载失败（所有候选均不可用）: {char_name}")
            return None

        try:
            from io import BytesIO
            img = Image.open(BytesIO(data)).convert("RGBA")
        except Exception:
            return None

        # 降采样：限制最大高度，保留宽高比（max_height = 0 表示保留原画质）
        max_h = int(self._art_preset.get("max_height", 0) or 0)
        if max_h and img.height > max_h:
            new_w = max(1, int(round(img.width * max_h / img.height)))
            img = img.resize((new_w, int(max_h)), Image.LANCZOS)

        os.makedirs(quality_dir, exist_ok=True)
        try:
            if self._elite1_art_ext() == "webp":
                # 画质参数来自当前档位（composer_config.PORTRAIT_QUALITY_PRESETS）
                quality = int(self._art_preset.get("quality", 90))
                quality = max(1, min(100, quality))
                img.save(local_path, "WEBP", quality=quality, method=6)
            else:
                img.save(local_path, "PNG", optimize=True)
        except Exception:
            return None
        return local_path

    async def _ensure_all_images(self, results: List[dict]):
        """并发下载十连中所有需要的半身像和职业图标"""
        # 干员数据可能在插件运行期间被自动更新器刷新，这里按需重载职业映射，
        # 避免"新干员抽得到、却因映射陈旧而缺职业图标"必须热重载才生效。
        self._refresh_professions_if_stale()

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
        self, result: dict, pool_name: str = "", is_new: bool = False,
    ) -> Optional[str]:
        """
        渲染单抽结果图片（元素表驱动构图，见 composer_config.SP3_ELEMENTS）。

        result:    {"name": str, "rarity": int, "is_up": bool}
        pool_name: 卡池名（用于文件名）
        is_new:    是否为首次获得该干员。True 时才绘制 NEW 标记；
                   当前尚未接入"首次抽到"判定，默认 False（即不显示）。

        构图包含：背景 + 精一立绘 + 阵营图标 + 带文字职业图标 + 星级五角星
                 + 中文名/英文名 + 装饰素材 + 椭圆暗角打光。
        各元素的位置 / 大小 / 层级全部由 composer_config.SP3_ELEMENTS 控制。
        立绘素材不可用（返回 None）时本方法返回 None，由调用方降级为纯文本。

        返回输出图片的本地路径，失败返回 None。
        """
        if not self._loaded:
            await self.initialize()

        # 清理过期的历史结果图，防止目录无限膨胀
        self._cleanup_output_dir()

        # 确保干员立绘已缓存（统一使用精英1立绘，缺失时兜底精英2立绘）
        elite1_path = await self._ensure_elite1_art(result["name"])
        if elite1_path is None:
            logger.warning(f"[ArkGacha] 单抽立绘不可用，跳过图片生成: {result['name']}")
            return None

        # 用合成器生成单抽图（元素表驱动）
        composer = self._get_composer()
        canvas = composer.compose_single_pull_v3(result, is_new=is_new)
        if canvas is None:
            return None

        # 保存：转 RGB 丢弃 alpha，确保输出完全不透明
        ts = int(time.time() * 1000)
        safe_name = pool_name.replace("/", "_").replace("\\", "_")[:30] if pool_name else "draw"
        filename = f"single_{safe_name}_{ts}.png"
        out_path = os.path.join(self.output_dir, filename)
        canvas.convert("RGB").save(out_path, "PNG")
        return out_path
