"""
astrbot_plugin_arknight_gacha_simulator
明日方舟抽卡模拟器 - 卡池查询、抽卡模拟、签到系统、潜能仓库
"""

import json
import os
import sys
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import AstrBotConfig, logger

# 插件唯一标识：用于向框架申请专属数据目录 data/plugin_data/<PLUGIN_NAME>/
PLUGIN_NAME = "astrbot_plugin_arknight_gacha_simulator"

# 中国时区
CST = timezone(timedelta(hours=8))

# 插件目录
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(PLUGIN_DIR, "Script")
# 强制把本插件目录置于 sys.path 最前：若其它插件也提供了同名模块，
# 必须保证优先命中本插件自己的实现（仅"不存在才插入"不足以应对这种情况）。
for p in (SCRIPT_DIR, PLUGIN_DIR):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

# ── 清理同名模块缓存（关键，勿删）─────────────────────────────────────────
# AstrBot 在同一进程内加载 / 热重载插件时，sys.modules 中可能残留【旧版本】
# 或【其它插件】的同名模块。此时 `import composer_config` 会直接命中缓存，
# 拿到的却是旧对象，表现为：
#     module 'composer_config' has no attribute 'set_data_dir'
# 进而导致插件在市场安装 / 更新后无法加载。
# 因此在首次导入前，先把本插件会用到的同名模块从缓存中剔除，
# 保证后续 import 一定解析到本插件 Script/ 目录下的实现。
_LOCAL_MODULES = (
    "composer_config", "text_render", "camp_logo_map", "font_manager",
    "plugin_migrate", "image_composer", "image_renderer", "gacha_engine",
    "database", "db_manager", "pool_generator", "auto_updater",
    "compose_background",
)
for _mod in _LOCAL_MODULES:
    sys.modules.pop(_mod, None)

import composer_config  # noqa: E402  运行时数据目录的统一来源

# 卡池封面图缓存 (30 天 TTL)
CACHE_TTL_DAYS = 30
POOL_CACHE_FILE = os.path.join(PLUGIN_DIR, "data", "cache", "pool_images.json")
# 卡池封面图本地存储目录：首次拉取后直接发本地文件，不再把 URL 交给下游加载
POOL_COVER_DIR = os.path.join(PLUGIN_DIR, "data", "cache", "pool_covers")

# ──────────────────── 辅助函数 ────────────────────


def _find_file(filename: str, search_in: List[str]) -> Optional[str]:
    for d in search_in:
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    return None


def parse_time(t_str: str) -> Optional[datetime]:
    if not t_str:
        return None
    try:
        return datetime.strptime(t_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=CST)
    except ValueError:
        return None


def pool_type_label(tid: str) -> str:
    labels = {
        "SINGLE": "限时单UP", "DOUBLE": "限时双UP/联合行动",
        "LIMITED": "限定寻访", "LINKAGE": "联动寻访",
        "NORM": "标准寻访", "CLASSIC": "中坚寻访",
        "SPECIAL": "定向甄选", "BOOT": "新人特惠",
        "ATTAIN": "跨年欢庆", "CLASSIC_ATTAIN": "跨年欢庆·中坚",
    }
    return labels.get(tid, tid)


def star_mark(rarity: int) -> str:
    """星级标注"""
    marks = {6: "(6★)", 5: "(5★)"}
    return marks.get(rarity, "")


def _format_time_display(t_str: str) -> str:
    """'2026-07-20 16:00' → '07.20 16:00'"""
    dt = parse_time(t_str)
    if dt:
        return dt.strftime("%m.%d %H:%M")
    return t_str


def get_prts_image_urls(pool_name: str, pool_type_id: str = "") -> List[str]:
    """
    根据卡池中文名和池型构造 PRTS 媒体缩略图 URL 列表（优先级排列）。

    所有池型均同时尝试 .jpg + .png，调用方可依次尝试取第一个可用的。
    """
    import hashlib
    from urllib.parse import quote

    def url_of(fn):
        md5_hex = hashlib.md5(fn.encode("utf-8")).hexdigest()
        return f"https://media.prts.wiki/thumb/{md5_hex[0]}/{md5_hex[:2]}/{quote(fn, safe='')}/600px-{quote(fn, safe='')}"

    def split_num(s):
        st = s.rstrip("0123456789").rstrip("_")
        n = s[len(st):].lstrip("_") if st != s else ""
        return st, n

    def punc_under(s):
        for ch in "·：:（）() 【】":
            s = s.replace(ch, "_")
        return s

    def strip_bracket(s):
        """剥离池名开头的【...】前缀（如【限定寻访·夏季】车辙与风的归所 → 车辙与风的归所）。
        PRTS 封面图文件名通常使用去掉该前缀后的事件名。"""
        if "】" in s:
            s = s.split("】", 1)[1]
        return s

    names = []

    if pool_type_id == "NORM":
        _, num = split_num(punc_under(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"干员轮换卡池{num}{ext}")

    elif pool_type_id == "CLASSIC":
        _, num = split_num(punc_under(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"中坚干员轮换卡池{num}{ext}")

    elif pool_type_id == "DOUBLE":
        s, num = split_num(punc_under(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"{s}{num}{ext}")

    elif pool_type_id == "SINGLE":
        base = punc_under(strip_bracket(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"{base}{ext}")

    elif pool_type_id == "LINKAGE":
        base = punc_under(strip_bracket(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"{base}{ext}")

    elif pool_type_id == "SPECIAL":
        _, num = split_num(punc_under(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"定向甄选{num}{ext}")

    elif pool_type_id == "BOOT":
        for ext in (".jpg", ".png"):
            names.append(f"专属推荐干员寻访{ext}")

    elif pool_type_id == "LIMITED":
        event = pool_name.split("】", 1)[1] if "】" in pool_name else pool_name
        for ext in (".jpg", ".png"):
            names.append(f"{event}{ext}")

    elif pool_type_id == "ATTAIN":
        base = strip_bracket(pool_name)
        for ext in (".jpg", ".png"):
            names.append(f"{base}{ext}")

    elif pool_type_id == "CLASSIC_ATTAIN":
        base = punc_under(strip_bracket(pool_name))
        for num in ("03", "02", "01", "04", "05"):
            for ext in (".jpg", ".png"):
                names.append(f"{base}{num}{ext}")

    else:
        base = punc_under(strip_bracket(pool_name))
        for ext in (".jpg", ".png"):
            names.append(f"{base}{ext}")

    return [url_of(fn) for fn in names]


# ──────────────────── 插件类 ────────────────────


class ArknightsGacha(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        # 向框架申请插件专属数据目录，并注入给配置模块。
        # 所有运行时数据（下载缓存 / 抓取数据 / 字体 / 数据库）都存放于该目录：
        #   · 不污染 AstrBot 的 data/ 根目录
        #   · 不写入插件安装目录（插件目录属于只读资源区，随更新会被整体覆盖）
        global POOL_CACHE_FILE, POOL_COVER_DIR, DATA_DIR
        DATA_DIR = str(StarTools.get_data_dir(PLUGIN_NAME))
        # 兼容旧版本：迁移历史遗留数据，避免老用户升级后丢失抽卡次数 /
        # 签到记录 / 潜能仓库。迁移内容与访问范围见 plugin_migrate 模块说明。
        try:
            from plugin_migrate import ensure_migrated
            ensure_migrated()
        except Exception as e:
            logger.warning(f"[ArkGacha] 旧数据迁移检查失败（忽略）: {e}")
        composer_config.set_data_dir(DATA_DIR)
        # 预先建好运行时数据子目录：tools/ 下的数据拉取脚本会直接向 raw/、
        # processed/ 写文件，若目录不存在会因 [Errno 2] 写入失败，
        # 进而导致卡池数据永远拉不下来、抽卡引擎无法初始化。
        composer_config.ensure_data_dirs()
        POOL_CACHE_FILE = os.path.join(DATA_DIR, "cache", "pool_images.json")
        POOL_COVER_DIR = os.path.join(DATA_DIR, "cache", "pool_covers")

        # 数据
        self.pools: List[Dict] = []
        self.active_pools: List[Dict] = []
        self.base_pools: Dict = {}

        # 模块
        self.engine = None
        self.db = None
        self.updater = None
        self.renderer = None  # 图片渲染器
        # 自动更新器的启动任务。必须持有引用：事件循环对 Task 只持弱引用，
        # 不保存的话它可能在 await 期间被 GC 回收，导致首次数据拉取静默失败。
        self._updater_task: Optional[asyncio.Task] = None
        # 数据缺失时触发的后台恢复任务（本地重建 + 必要时联网拉取），同样须持引用
        self._recover_task: Optional[asyncio.Task] = None

        # 状态
        self._loaded = False
        self._error = ""

    # ──────────────────── 生命周期 ────────────────────

    async def initialize(self):
        """插件加载时调用"""
        logger.info("[ArkGacha] 正在初始化...")

        try:
            # 1. 加载卡池数据
            self._load_pool_data()

            # 2. 生成/加载 active_pools
            self._load_active_pools()

            # 3. 初始化数据库
            self._init_database()

            # 4. 初始化抽卡引擎（放线程：数据缺失时会同步拉起子进程，最长 60s）
            await asyncio.to_thread(self._init_engine)

            # 5. 准备字体资源（缺失时从官方源下载并缓存；失败仅告警）
            await self._init_fonts()

            # 6. 初始化图片渲染器
            await self._init_renderer()

            # 7. 启动自动更新
            self._start_updater()

            self._loaded = True
            logger.info(f"[ArkGacha] 初始化完成 ({len(self.active_pools)} 个进行中卡池)")

        except Exception as e:
            self._error = str(e)
            logger.error(f"[ArkGacha] 初始化失败: {e}", exc_info=True)

    async def terminate(self):
        """插件卸载时调用"""
        if self.updater:
            try:
                await self.updater.stop()
            except Exception:
                pass
        if self._updater_task and not self._updater_task.done():
            self._updater_task.cancel()
            try:
                await self._updater_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._updater_task = None
        if self._recover_task and not self._recover_task.done():
            self._recover_task.cancel()
            try:
                await self._recover_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._recover_task = None
        self.pools = []
        self.active_pools = []
        self._loaded = False
        logger.info("[ArkGacha] 已卸载")

    # ──────────────────── 初始化子步骤 ────────────────────

    def _load_pool_data(self):
        """加载 cleaned_pools_final.json

        首次运行/数据缺失时**不抛异常**：卡池数据由自动更新器（AutoUpdater）首次启动时
        从 GitHub / PRTS 拉取并通过全量流水线生成。这里先置空并记录提示，
        待 updater 生成数据后通过 on_after_update 回调重新加载。
        """
        candidates = [
            composer_config.PROCESSED_DIR,
        ]
        path = _find_file("cleaned_pools_final.json", candidates)
        if not path:
            logger.info(
                "[ArkGacha] 未找到 cleaned_pools_final.json，等待自动更新器首次拉取生成卡池数据"
            )
            self.pools = []
            return
        # 读取失败（文件损坏 / 写入被中断）不能向外抛：initialize 的 try 一旦被
        # 穿透，self._loaded 就永远停在 False，所有指令会一直提示"插件数据未加载"。
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.pools = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"[ArkGacha] 卡池数据读取失败（等待重新生成）: {e}")
            self.pools = []
            return
        logger.info(f"[ArkGacha] 已加载 {len(self.pools)} 个卡池")
        logger.info(f"[ArkGacha] 已加载 {len(self.pools)} 个卡池数据")

    def _load_active_pools(self):
        """加载/重新生成 active_pools.json"""
        active_path = os.path.join(composer_config.PROCESSED_DIR, "active_pools.json")

        # 尝试重新生成（对比当前时间）
        try:
            from pool_generator import generate_active_pools
            pools_path = _find_file("cleaned_pools_final.json", [
                composer_config.PROCESSED_DIR,
            ])
            if pools_path:
                active_data = generate_active_pools(pools_path)
                os.makedirs(os.path.dirname(active_path), exist_ok=True)
                with open(active_path, "w", encoding="utf-8") as f:
                    json.dump(active_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[ArkGacha] 已生成 active_pools.json ({len(active_data)} 个进行中)")
        except Exception as e:
            logger.warning(f"[ArkGacha] 重新生成 active_pools 失败: {e}, 尝试读取已有文件")

        # 读取（同样不能向外抛，否则会穿透 initialize 的 try 使 _loaded 恒为 False）
        if os.path.isfile(active_path):
            try:
                with open(active_path, "r", encoding="utf-8") as f:
                    self.active_pools = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"[ArkGacha] active_pools.json 损坏，已重置为空: {e}")
                self.active_pools = []
        else:
            self.active_pools = []

    def _init_database(self):
        """初始化 SQLite 数据库（存放于框架分配的插件专属数据目录）"""
        try:
            from db_manager import DBManager

            # data/plugin_data/<插件名>/user.db
            db_dir = DATA_DIR
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "user.db")

            self.db = DBManager(db_path)
            logger.info(f"[ArkGacha] 数据库已初始化 ({db_path})")
        except Exception as e:
            logger.error(f"[ArkGacha] 数据库初始化失败: {e}")
            self.db = None

    def _init_engine(self, allow_generate: bool = True):
        """初始化抽卡概率引擎

        allow_generate: 数据文件缺失时是否允许在本进程内即时生成。
                        该生成会【同步】拉起一个子进程（timeout=60），所以只能在
                        启动 / 数据更新等非交互路径上传 True；
                        指令路径（_check_loaded）必须传 False —— 否则单个请求就能
                        把事件循环卡住最长 60 秒。
        """
        bp_path = os.path.join(composer_config.PROCESSED_DIR, "base_pools.json")
        rules_path = os.path.join(composer_config.PROCESSED_DIR, "pool_rules.json")

        if allow_generate and (not os.path.isfile(bp_path)
                               or not os.path.isfile(rules_path)):
            # 尝试自动生成（依赖已拉取的卡池 / 干员数据）
            try:
                import subprocess, sys
                gen_path = os.path.join(SCRIPT_DIR, "pool_generator.py")
                proc = subprocess.run(
                    [sys.executable, gen_path, "--base-only"],
                    cwd=SCRIPT_DIR, capture_output=True, timeout=60,
                )
                if proc.returncode == 0:
                    logger.info("[ArkGacha] 已自动生成 base_pools.json")
            except Exception as e:
                logger.warning(f"[ArkGacha] 自动生成 base_pools 失败: {e}")

        try:
            from gacha_engine import GachaEngine
            self.engine = GachaEngine(bp_path, rules_path)
            logger.info("[ArkGacha] 抽卡引擎已初始化")
        except Exception as e:
            # 首次运行时数据尚未拉取，走到这里是预期情况：
            # 自动更新器完成拉取后会通过 on_after_update 回调重新初始化引擎。
            self.engine = None
            if os.path.isfile(bp_path) and os.path.isfile(rules_path):
                logger.error(f"[ArkGacha] 引擎初始化失败: {e}")
            else:
                logger.info("[ArkGacha] 卡池数据尚未就绪，等待自动更新完成后重建引擎")

    async def _init_fonts(self):
        """
        确保文字渲染所需的字体现已就绪。

        字体【不随插件包分发】（以控制插件包体积），首次运行时从
        OpenHarmony 官方仓库下载、做 SHA-256 校验后缓存到 data/fonts/，
        后续启动直接复用。任何失败都只告警：字体缺失时结果图不绘制文字，
        其余功能不受影响，绝不阻断插件启动。
        """
        try:
            from font_manager import ensure_fonts
            await ensure_fonts()
        except Exception as e:
            logger.warning(f"[ArkGacha] 字体准备失败（不影响其它功能）: {e}")

    async def _init_renderer(self):
        """初始化图片渲染器"""
        try:
            from image_renderer import ImageRenderer
            # 立绘缓存画质档位（AstrBot 配置页选择，默认原画质）
            quality = ""
            if self.config:
                quality = str(self.config.get("portrait_cache_quality", "") or "")
            self.renderer = ImageRenderer(PLUGIN_DIR, portrait_quality=quality)
            await self.renderer.initialize()
            logger.info("[ArkGacha] 图片渲染器已初始化")
        except Exception as e:
            logger.warning(f"[ArkGacha] 图片渲染器初始化失败（图片功能不可用）: {e}")
            self.renderer = None

    def _reload_renderer_professions(self):
        """
        刷新渲染器的 干员→职业 映射。

        干员数据由自动更新器刷新后调用，使新干员的职业图标立即可用，
        避免必须热重载插件才能生效。
        """
        if not self.renderer:
            return
        try:
            count = self.renderer.reload_professions()
            logger.info(f"[ArkGacha] 渲染器职业映射已刷新（{count} 条）")
        except Exception as e:
            logger.warning(f"[ArkGacha] 刷新渲染器职业映射失败: {e}")

    def _start_updater(self):
        """启动自动更新器（受 auto_update 配置控制，默认开启）"""
        auto_update = bool(self.config.get("auto_update", True)) if self.config else True
        if not auto_update:
            logger.info("[ArkGacha] auto_update 已关闭，跳过自动更新器")
            return
        try:
            from auto_updater import AutoUpdater

            async def on_after_update():
                """数据更新后的回调：重新加载所有数据（放线程，避免阻塞事件循环）"""
                logger.info("[ArkGacha] 数据已更新，重新加载...")

                def _reload_all():
                    self._load_pool_data()
                    self._load_active_pools()
                    self._init_engine()
                    # 同步刷新渲染器的职业映射（否则新干员的职业图标要等热重载才生效）
                    self._reload_renderer_professions()

                await asyncio.to_thread(_reload_all)

            self.updater = AutoUpdater(
                PLUGIN_DIR,
                on_after_update=on_after_update,
            )

            # 在事件循环中启动
            try:
                loop = asyncio.get_running_loop()
                # 持有引用，避免任务在 await（网络请求）期间被垃圾回收
                self._updater_task = loop.create_task(self.updater.start())
                logger.info("[ArkGacha] 自动更新器已启动")
            except RuntimeError:
                logger.warning("[ArkGacha] 无运行中的事件循环，跳过自动更新启动")

        except ImportError as e:
            logger.warning(f"[ArkGacha] 自动更新器加载失败 (缺少依赖?): {e}")
        except Exception as e:
            logger.warning(f"[ArkGacha] 自动更新器启动失败: {e}")

    # ──────────────────── 通用校验 ────────────────────

    @staticmethod
    def _load_pool_cache() -> dict:
        """加载 pool_images.json 缓存 (以池名为 key)"""
        try:
            with open(POOL_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @classmethod
    def _save_pool_cache(cls, pool_name: str, url: str,
                         file_name: Optional[str] = None):
        """
        写入/更新 pool_images.json 缓存，同时清理超期条目。

        file_name: 本地封面文件名（相对 POOL_COVER_DIR）。
                   传 None 时保留该池已有的 file 字段，避免 URL 探测
                   （_find_valid_url）把已下载好的本地文件记录覆盖掉。
        """
        try:
            os.makedirs(os.path.dirname(POOL_CACHE_FILE), exist_ok=True)
            data = cls._load_pool_cache()
            existing = data.get(pool_name)
            if file_name is None and isinstance(existing, dict):
                file_name = existing.get("file")
            data[pool_name] = {
                "url": url,
                "file": file_name,
                "cached_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            }
            # 清理超期条目，防止缓存文件无限膨胀
            now = datetime.now(CST)
            expired = []
            for k, v in data.items():
                if isinstance(v, dict) and v.get("cached_at"):
                    try:
                        cached_at = datetime.strptime(
                            v["cached_at"], "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=CST)
                    except ValueError:
                        expired.append(k)
                        continue
                    if (now - cached_at).days >= CACHE_TTL_DAYS:
                        expired.append(k)
            for k in expired:
                v = data.pop(k, None)
                # 连同本地封面文件一起回收，避免目录里留下孤儿文件
                if isinstance(v, dict) and v.get("file"):
                    try:
                        os.remove(os.path.join(POOL_COVER_DIR, v["file"]))
                    except OSError:
                        pass
            with open(POOL_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    async def _find_valid_url(self, urls: List[str], pool_name: str = "") -> Optional[str]:
        """
        依次尝试 URL，返回第一个可达的（轻量 HEAD 检查）。
        带 30 天本地缓存：命中且未超期直接返回缓存 URL，减少 PRTS 请求压力。
        """
        # 1. 命中缓存且未超期 → 直接返回
        if pool_name:
            cache = self._load_pool_cache()
            entry = cache.get(pool_name)
            if isinstance(entry, dict) and entry.get("url"):
                try:
                    cached_at = datetime.strptime(
                        entry["cached_at"], "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=CST)
                except (KeyError, ValueError):
                    cached_at = None
                if cached_at and (datetime.now(CST) - cached_at).days < CACHE_TTL_DAYS:
                    return entry["url"]

        # 2. 缓存 miss/超期 → HEAD 逐个探测
        import aiohttp
        for url in urls:
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    async with sess.head(url) as resp:
                        if resp.status == 200:
                            if pool_name:
                                self._save_pool_cache(pool_name, url)
                            return url
            except Exception:
                continue
        return None

    # ──────────────────── 卡池封面本地化 ────────────────────

    @staticmethod
    def _safe_cover_filename(pool_name: str, ext: str = "png") -> str:
        """把卡池名转成安全的文件名（剔除路径非法字符，超长截断）"""
        import re
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", pool_name).strip(" ._")
        if not safe:
            safe = hashlib.md5(pool_name.encode("utf-8")).hexdigest()[:16]
        return f"{safe[:80]}.{ext}"

    @staticmethod
    def _pool_cache_fresh(entry) -> bool:
        """缓存条目是否仍在有效期内（默认 30 天）"""
        if not isinstance(entry, dict) or not entry.get("cached_at"):
            return False
        try:
            cached_at = datetime.strptime(
                entry["cached_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        except ValueError:
            return False
        return (datetime.now(CST) - cached_at).days < CACHE_TTL_DAYS

    async def _download_first_available(self, urls: List[str]):
        """
        依次尝试下载候选 URL，返回 (bytes, url, 图片格式)；全部失败返回 (None, None, None)。

        直接 GET 而非 HEAD+GET：封面图体积很小，
        一次请求即可同时完成"可达性验证 + 取数据"，请求数减半。
        """
        import aiohttp
        from io import BytesIO
        from PIL import Image

        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                for url in urls:
                    try:
                        async with sess.get(url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.read()
                            if not data:
                                continue
                            try:
                                img = Image.open(BytesIO(data))
                                fmt = (img.format or "").upper()
                                img.verify()
                            except Exception:
                                continue
                            return data, url, fmt
                    except Exception:
                        continue
        except Exception:
            pass
        return None, None, None

    async def _fetch_pool_cover(self, pool_name: str,
                                urls: List[str]) -> Optional[str]:
        """探测并下载卡池封面到本地，成功后写缓存并返回本地路径"""
        entry = self._load_pool_cache().get(pool_name)
        candidates: List[str] = []
        if isinstance(entry, dict) and entry.get("url"):
            candidates.append(entry["url"])
        for u in urls:
            if u and u not in candidates:
                candidates.append(u)
        if not candidates:
            return None

        data, used_url, fmt = await self._download_first_available(candidates)
        if not data:
            return None

        ext = "jpg" if fmt in ("JPEG", "JPG") else "png"
        file_name = self._safe_cover_filename(pool_name, ext)
        try:
            os.makedirs(POOL_COVER_DIR, exist_ok=True)
            with open(os.path.join(POOL_COVER_DIR, file_name), "wb") as f:
                f.write(data)
        except OSError as e:
            logger.warning(f"[ArkGacha] 卡池封面写入失败: {e}")
            return None

        self._save_pool_cache(pool_name, used_url, file_name)
        return os.path.join(POOL_COVER_DIR, file_name)

    async def _get_pool_cover_path(self, pool_name: str,
                                   urls: List[str]) -> Optional[str]:
        """
        取卡池封面的【本地】路径：下载一次、存 30 天，之后直接发本地文件。

        与旧行为（每次把 URL 传给下游、由平台去 PRTS 加载）的区别：
        图片从"下游每次现取"变为"插件本地持有"，
        既不再让下游承担加载压力，也不再依赖 PRTS 的实时可用性。

        策略：
          1. 本地文件存在且未超期 → 直接返回
          2. 已超期               → 尝试刷新；刷新失败则继续用旧图（有图好过没图）
          3. 本地缺失             → 探测 + 下载 + 落盘 + 写缓存
          4. 全部失败             → 返回 None，由调用方回退旧行为
        """
        if not pool_name or not urls:
            return None
        try:
            entry = self._load_pool_cache().get(pool_name)
            if isinstance(entry, dict) and entry.get("file"):
                local = os.path.join(POOL_COVER_DIR, entry["file"])
                if os.path.isfile(local):
                    if self._pool_cache_fresh(entry):
                        return local
                    refreshed = await self._fetch_pool_cover(pool_name, urls)
                    return refreshed or local
            return await self._fetch_pool_cover(pool_name, urls)
        except Exception as e:
            logger.warning(f"[ArkGacha] 获取卡池封面失败: {e}")
            return None

    def _check_loaded(self) -> Optional[str]:
        """返回错误信息或 None

        时序修复: 首次初始化时 auto_updater 是异步生成数据的，
        命令可能先于数据生成而触发。因此在检查前先尝试从磁盘刷新
        active_pools 与抽卡引擎，避免出现"卡池查询为空"。
        """
        if not self._loaded:
            return "插件数据未加载，请稍后再试。"

        if not self.active_pools:
            try:
                self._load_active_pools()
            except Exception as e:
                logger.warning(f"[ArkGacha] 刷新 active_pools 失败: {e}")

        # 剔除已结束的卡池（active_pools 不会随时间自动刷新，见方法内说明）
        try:
            self._prune_expired_active_pools()
        except Exception as e:
            logger.warning(f"[ArkGacha] 卡池时效校验失败: {e}")

        if not self.engine:
            try:
                # 指令路径不做【同步】即时生成（会拉起子进程阻塞最长 60s），
                # 只尝试加载现有文件；缺失则走下面的后台恢复。
                self._init_engine(allow_generate=False)
            except Exception as e:
                logger.warning(f"[ArkGacha] 刷新抽卡引擎失败: {e}")

        # 数据尚未就绪（首次安装 / 数据未生成）→ 主动在后台补齐，而不是让用户干等
        pools_file = os.path.join(composer_config.PROCESSED_DIR,
                                  "cleaned_pools_final.json")
        data_missing = not os.path.isfile(pools_file)
        if data_missing or not self.active_pools or not self.engine:
            self._schedule_data_recovery()

        if not self.active_pools:
            if data_missing:
                return "卡池数据尚未就绪，已在后台开始拉取，请稍等片刻后再试。"
            return "当前没有进行中的卡池，无法抽卡。"
        if not self.engine:
            return "抽卡引擎数据正在后台生成，请稍等片刻后再试。"
        if not self.db:
            return "数据库未就绪。"
        return None

    def _schedule_data_recovery(self) -> None:
        """数据缺失时在后台触发一次恢复（本地重建 → 必要时联网拉取）。

        由 _check_loaded 在发现"卡池数据 / 抽卡引擎未就绪"时调用，
        目的是主动把数据补齐，而不是让用户干等或反复重试。

        不阻塞当前请求；同一时刻只允许一个恢复任务在跑
        （自带去重，多个用户同时触发也只会跑一次）。
        """
        if self._recover_task and not self._recover_task.done():
            return                              # 已有恢复任务在进行中
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                              # 无运行中的事件循环（不应发生）

        async def _recover():
            try:
                # 1. 用本地数据重建引擎产物（纯本地解析；放线程避免阻塞事件循环）
                await asyncio.to_thread(self._init_engine)
                # 2. 本地连卡池原始数据都没有 → 才去联网拉取
                pools_file = os.path.join(composer_config.PROCESSED_DIR,
                                          "cleaned_pools_final.json")
                if not os.path.isfile(pools_file) and self.updater is not None:
                    logger.info("[ArkGacha] 本地卡池数据缺失，主动触发一次拉取...")
                    await self.updater.check_and_update()
            except Exception as e:
                logger.warning(f"[ArkGacha] 后台数据恢复失败: {e}")

        try:
            self._recover_task = loop.create_task(_recover())
            logger.info("[ArkGacha] 已在后台触发数据恢复")
        except Exception as e:
            logger.warning(f"[ArkGacha] 触发数据恢复失败: {e}")

    def _prune_expired_active_pools(self) -> None:
        """剔除内存中已经结束的卡池。

        active_pools 是"生成那一刻"的时间切片，此后不随时间的推移自动刷新；
        而【旧池结束】不会触发数据更新（PRTS 与本地文件会同时把它排除，
        被判定为"一致"），于是它会一直留在内存里 —— 已结束的卡池仍可被抽到。
        这里在使用前按 time_end 主动剔除。

        仅当确有卡池过期时才重排编号（保持 1~N 连续），避免频繁变动用户
        已经记住的卡池编号。
        """
        if not self.active_pools:
            return

        now = datetime.now(CST)
        kept, expired = [], 0
        for p in self.active_pools:
            try:
                end = datetime.strptime(
                    str(p.get("time_end", "")).strip(), "%Y-%m-%d %H:%M"
                ).replace(tzinfo=CST)
            except (ValueError, TypeError):
                kept.append(p)   # 时间无法解析时保留，避免误剔除
                continue
            if now > end:
                expired += 1
                continue
            kept.append(p)

        if not expired:
            return

        for idx, p in enumerate(kept, start=1):
            p["active_id"] = idx
        self.active_pools = kept
        logger.info(
            f"[ArkGacha] 已剔除 {expired} 个已结束的卡池，剩余 {len(kept)} 个")

        if not kept:
            # 本地数据里可能已有新池，重新筛选一次
            try:
                self._load_active_pools()
            except Exception as e:
                logger.warning(f"[ArkGacha] 重新生成 active_pools 失败: {e}")

    def _find_active_pool(self, pool_num: int) -> Optional[Dict]:
        """从 active_pools 中按编号查找卡池"""
        for p in self.active_pools:
            if p.get("active_id") == pool_num:
                return p
        return None

    # ════════════════════════════════════════════════
    #  ========== 新指令: 抽卡帮助 ==========
    # ════════════════════════════════════════════════

    @filter.command("抽卡帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示所有抽卡命令及描述"""
        yield event.plain_result(
            "[明日方舟抽卡模拟器]\n"
            "━━━━━━━━━━━━━━\n"
            "/抽卡帮助          显示本帮助\n"
            "/抽卡签到          每日签到，领取 10 次抽卡机会\n"
            "/单抽 <池编号>     在指定卡池进行一次单抽\n"
            "/十连 <池编号>     在指定卡池进行一次十连抽卡\n"
            "/卡池查询          查看当前进行中的卡池\n"
            "/潜能仓库          查看已获得的干员及潜能数\n"
            "/潜能仓库 <星级>   查看指定星级干员（分页显示）\n"
            "/潜能仓库 <星级> <页码>  翻页查看\n"
        )

    # ════════════════════════════════════════════════
    #  ========== 新指令: 抽卡签到 ==========
    # ════════════════════════════════════════════════

    @filter.command("抽卡签到")
    async def cmd_sign_in(self, event: AstrMessageEvent):
        """每日签到，领取 10 次抽卡机会"""
        if not self.db:
            yield event.plain_result("[抽卡签到] 数据库未就绪，请联系管理员。")
            return

        user_id = event.get_sender_id()

        ok, remaining = self.db.do_sign_in(user_id, amount=10)

        if ok:
            yield event.plain_result(
                f"[抽卡签到] 签到成功! +10 次抽卡机会\n"
                f"当前剩余抽卡次数: {remaining}"
            )
        else:
            yield event.plain_result(
                f"[抽卡签到] 今天已经签到过啦！\n"
                f"当前剩余抽卡次数: {remaining}"
            )

    # ════════════════════════════════════════════════
    #  ========== 新指令: 单抽 ==========
    # ════════════════════════════════════════════════

    @filter.command("单抽")
    async def cmd_single_pull(self, event: AstrMessageEvent):
        """在指定卡池进行一次单抽。用法: /单抽 <池编号>"""
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        # 解析参数
        parts = event.message_str.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            yield event.plain_result("用法: /单抽 <池编号>\n示例: /单抽 1\n请先使用 /卡池查询 查看可用编号。")
            return

        pool_num = int(parts[1])
        pool = self._find_active_pool(pool_num)
        if not pool:
            yield event.plain_result(f"未找到编号为 {pool_num} 的卡池。请使用 /卡池查询 查看当前可用卡池。")
            return

        user_id = event.get_sender_id()

        # 检查次数
        if self.db.get_draw_count(user_id) <= 0:
            yield event.plain_result(
                "抽卡次数不足！\n"
                "请使用 /抽卡签到 领取每日 10 次抽卡机会。"
            )
            return

        # 获取当前计数器
        i, j = self.db.get_counters(user_id)

        # 获取 UP 干员名列表
        ops_6 = [o["name"] for o in pool.get("operators_6", [])]
        ops_5 = [o["name"] for o in pool.get("operators_5", [])]
        pool_type = pool["pool_type_id"]

        # 已持有干员名列表（供 ATTAIN / CLASSIC_ATTAIN 的"首次6★必定未持有"保护使用）
        owned = [c["char_name"] for c in self.db.get_user_characters(user_id)]

        # 抽卡
        result, new_i, new_j = self.engine.single_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
            owned_characters=owned,
        )

        # 首发十连五星保底: 累计第10抽 且 前10抽从未出≥5★ 且 本抽<5★ → 强制替换为5★
        if self.db.check_first_ten_trigger(user_id, pool["active_id"], result["rarity"]):
            result, new_i, new_j = self.engine.single_pull(
                pool_type, ops_6, ops_5, i, j,
                select_rules=pool.get("select_rules"),
                owned_characters=owned,
                force_rarity=5,
            )

        # 更新数据库
        self.db.update_counters(user_id, new_i, new_j, draw_consumed=1)
        self.db.add_character(user_id, result["name"], result["rarity"])
        self.db.increment_pull_count(user_id, pool["active_id"], result["rarity"])

        # 格式化输出
        star_label = star_mark(result["rarity"])
        up_tag = " [UP]" if result["is_up"] else ""
        # 该池累计抽数（已含本次）
        pool_pulls = self.db.get_pool_pull_count(user_id, pool["active_id"])

        text = (
            f"[单抽结果] 池{pool_num}「{pool['pool_name']}」\n"
            f"{result['rarity']}★ {result['name']} {star_label}{up_tag}\n"
            f"本池累计抽数: {pool_pulls}"
        )

        # 尝试生成图片
        image_path = None
        if self.renderer:
            try:
                image_path = await self.renderer.render_single_pull(
                    result, pool["pool_name"]
                )
            except Exception as e:
                logger.warning(f"[ArkGacha] 单抽图片生成失败: {e}")

        if image_path and os.path.isfile(image_path):
            yield event.make_result().message(text).file_image(image_path)
        else:
            yield event.plain_result(text)

    # ════════════════════════════════════════════════
    #  ========== 新指令: 十连 ==========
    # ════════════════════════════════════════════════

    @filter.command("十连")
    async def cmd_ten_pull(self, event: AstrMessageEvent):
        """在指定卡池进行一次十连抽卡。用法: /十连 <池编号>"""
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            yield event.plain_result("用法: /十连 <池编号>\n示例: /十连 1\n请先使用 /卡池查询 查看可用编号。")
            return

        pool_num = int(parts[1])
        pool = self._find_active_pool(pool_num)
        if not pool:
            yield event.plain_result(f"未找到编号为 {pool_num} 的卡池。请使用 /卡池查询 查看当前可用卡池。")
            return

        user_id = event.get_sender_id()

        # 检查次数
        if self.db.get_draw_count(user_id) < 10:
            yield event.plain_result(
                f"抽卡次数不足！需要 10 次，当前剩余 {self.db.get_draw_count(user_id)} 次。\n"
                "请使用 /抽卡签到 领取每日 10 次抽卡机会。"
            )
            return

        # 获取计数器
        i, j = self.db.get_counters(user_id)

        ops_6 = [o["name"] for o in pool.get("operators_6", [])]
        ops_5 = [o["name"] for o in pool.get("operators_5", [])]
        pool_type = pool["pool_type_id"]

        # 首发保底状态: (累计抽数, 是否已出过≥5★)
        first_start, first_seen = self.db.get_first_ten_state(user_id, pool["active_id"])

        # 已持有干员名列表（供 ATTAIN / CLASSIC_ATTAIN 的"首次6★必定未持有"保护使用）
        owned = [c["char_name"] for c in self.db.get_user_characters(user_id)]

        # 十连 (引擎内处理首发十连五星保底: 全局第10抽若<5★则强制替换为5★)
        results, new_i, new_j = self.engine.ten_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
            owned_characters=owned,
            first_ten_start=first_start,
            first_ten_seen=first_seen,
        )

        # 更新数据库
        self.db.update_counters(user_id, new_i, new_j, draw_consumed=10)
        for r in results:
            self.db.add_character(user_id, r["name"], r["rarity"])
            self.db.increment_pull_count(user_id, pool["active_id"], r["rarity"])

        # 格式化输出（文本 + 图片）
        lines = [f"[十连结果] 池{pool_num}「{pool['pool_name']}」"]
        for idx, r in enumerate(results, 1):
            star_label = star_mark(r["rarity"])
            up_mark = " [UP]" if r["is_up"] else ""
            lines.append(f"  {idx:2d}. {r['rarity']}★ {r['name']} {star_label}{up_mark}")

        # 统计
        counts = {}
        for r in results:
            counts[r["rarity"]] = counts.get(r["rarity"], 0) + 1
        summary_parts = []
        for s in [6, 5, 4, 3]:
            if s in counts:
                summary_parts.append(f"{s}★x{counts[s]}")
        lines.append(f"  统计: {', '.join(summary_parts)}")

        remaining = self.db.get_draw_count(user_id)
        lines.append(f"  剩余次数: {remaining}")

        # 该池累计抽数（已含本次十连）
        pool_pulls = self.db.get_pool_pull_count(user_id, pool["active_id"])
        lines.append(f"  本池累计抽数: {pool_pulls}")

        # 尝试生成图片
        image_path = None
        if self.renderer:
            try:
                image_path = await self.renderer.render_ten_pull(
                    results, pool["pool_name"]
                )
            except Exception as e:
                logger.warning(f"[ArkGacha] 十连图片生成失败: {e}")

        if image_path and os.path.isfile(image_path):
            yield event.make_result().message("\n".join(lines)).file_image(image_path)
        else:
            yield event.plain_result("\n".join(lines))

    # ════════════════════════════════════════════════
    #  ========== 新指令: 卡池查询 ==========
    # ════════════════════════════════════════════════

    @filter.command("卡池查询")
    async def cmd_pool_query(self, event: AstrMessageEvent):
        """查看当前进行中的卡池（含 PRTS 卡池封面）"""
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        if not self.active_pools:
            yield event.plain_result("当前没有进行中的卡池。")
            return

        # 标题
        yield event.plain_result(
            f"[当前进行中的卡池] 共 {len(self.active_pools)} 个"
        )

        for p in self.active_pools:
            aid = p["active_id"]
            name = p["pool_name"]
            pool_type = p["pool_type_id"]
            t_start = _format_time_display(p.get("time_start", ""))
            t_end = _format_time_display(p.get("time_end", ""))

            lines = [
                f"池{aid}: 《{name}》({pool_type_label(pool_type)})",
                f"  时间: {t_start} ~ {t_end}",
            ]

            # UP 干员
            ops_6 = p.get("operators_6", [])
            ops_5 = p.get("operators_5", [])

            if p.get("pool_contents"):
                names_6 = [o["name"] for o in ops_6]
                lines.append(f"  池内6星: {', '.join(names_6[:5])}{'...' if len(names_6) > 5 else ''} ({len(names_6)}人)")
                if p.get("first_6star_dup_protection"):
                    lines.append(f"  特规: 首次6星必定未持有")
            elif p.get("select_rules"):
                names_6 = [o["name"] for o in ops_6]
                names_5 = [o["name"] for o in ops_5]
                lines.append(f"  6星候选: {', '.join(names_6)} ({len(names_6)}选3)")
                lines.append(f"  5星候选: {', '.join(names_5)} ({len(names_5)}选3)")
            else:
                if ops_6:
                    shop = [o["name"] for o in ops_6 if o.get("shop")]
                    limited = [o["name"] for o in ops_6 if o.get("limited")]
                    basic = [o["name"] for o in ops_6 if not o.get("shop") and not o.get("limited")]
                    parts = []
                    if basic:
                        parts.append(f"UP: {', '.join(basic)}")
                    if shop:
                        parts.append(f"进店: {', '.join(shop)}")
                    if limited:
                        parts.append(f"限定: {', '.join(limited)}")
                    lines.append(f"  6星: {' | '.join(parts)}" if parts else f"  6星: {', '.join(o['name'] for o in ops_6)}")
                if ops_5:
                    shop5 = [o["name"] for o in ops_5 if o.get("shop")]
                    basic5 = [o["name"] for o in ops_5 if not o.get("shop")]
                    parts = []
                    if basic5:
                        parts.append(f"UP: {', '.join(basic5)}")
                    if shop5:
                        parts.append(f"进店: {', '.join(shop5)}")
                    lines.append(f"  5星: {' | '.join(parts)}" if parts else f"  5星: {', '.join(o['name'] for o in ops_5)}")

            text = "\n".join(lines)
            urls = get_prts_image_urls(name, pool_type)
            # 封面优先走本地缓存（下载一次存 30 天），不再把 URL 直接交给下游加载
            cover_path = await self._get_pool_cover_path(name, urls)
            if cover_path:
                yield event.make_result().message(text).file_image(cover_path)
            else:
                # 本地不可用 → 回退旧行为：探测可达 URL 直传
                valid_url = await self._find_valid_url(urls, name) if urls else None
                if valid_url:
                    yield event.make_result().message(text).url_image(valid_url)
                else:
                    yield event.plain_result(text)

    # ════════════════════════════════════════════════
    #  ========== 新指令: 潜能仓库 ==========
    # ════════════════════════════════════════════════

    @filter.command("潜能仓库")
    async def cmd_inventory(self, event: AstrMessageEvent):
        """查看已获得的干员及潜能数。支持分页：/潜能仓库 <星级> <页码>"""
        if not self.db:
            yield event.plain_result("[潜能仓库] 数据库未就绪。")
            return

        user_id = event.get_sender_id()
        parts = event.message_str.strip().split()

        # ---- 无参数：显示概要 + 使用提示 ----
        if len(parts) == 1:
            stats = self.db.get_user_stats(user_id)
            chars = self.db.get_user_characters(user_id)
            by_rarity = stats.get("by_rarity", {})

            lines = [
                f"[潜能仓库]\n"
                f"用户: {user_id}\n"
                f"历史总抽数: {stats['total_pulls']}    剩余次数: {stats['draw_count']}",
            ]
            for star in [6, 5, 4, 3]:
                info = by_rarity.get(star)
                if info:
                    lines.append(f"  {star}★: {info['unique']} 种 / {info['total']} 个")
                else:
                    lines.append(f"  {star}★: 暂无")

            lines.append(f"\n使用 /潜能仓库 <星级> <页码> 查看详情")
            lines.append(f"例: /潜能仓库 6 1  (六星第1页，每页10位，按潜能降序)")

            yield event.plain_result("\n".join(lines))
            return

        # ---- 有参数：分页展示 ----
        try:
            target_rarity = int(parts[1])
        except ValueError:
            yield event.plain_result("用法: /潜能仓库 <星级> 或 /潜能仓库 <星级> <页码>\n例: /潜能仓库 6    /潜能仓库 6 2")
            return

        if target_rarity not in (6, 5, 4, 3):
            yield event.plain_result("星级仅支持 3、4、5、6。例: /潜能仓库 6 1")
            return

        page = 1
        if len(parts) >= 3:
            try:
                page = max(1, int(parts[2]))
            except ValueError:
                page = 1

        page_size = 10
        chars = self.db.get_user_characters(user_id)
        filtered = [c for c in chars if c["rarity"] == target_rarity]
        # 按潜能数（count）降序排列
        filtered.sort(key=lambda c: c["count"], reverse=True)

        if not filtered:
            yield event.plain_result(f"[潜能仓库] 你还没有获得任何 {target_rarity}★ 干员。")
            return

        total = len(filtered)
        total_pages = (total + page_size - 1) // page_size
        page = min(page, total_pages)

        start = (page - 1) * page_size
        end = start + page_size
        page_items = filtered[start:end]

        lines = [
            f"[潜能仓库] {target_rarity}★ 干员 (共 {total} 位，第 {page}/{total_pages} 页)",
        ]
        for c in page_items:
            lines.append(f"  {c['char_name']} x{c['count']}")

        if total_pages > 1:
            lines.append(f"\n使用 /潜能仓库 {target_rarity} <页码> 翻页")

        yield event.plain_result("\n".join(lines))

    # ════════════════════════════════════════════════
    #  ========== 管理员调试: 十连awa ==========
    # ════════════════════════════════════════════════

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("十连awa")
    async def cmd_debug_ten_pull(self, event: AstrMessageEvent):
        """
        管理员调试指令。无视次数限制进行十连，不记录数据库。
        用法: /十连awa <池编号>
        """
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            yield event.plain_result("用法: /十连awa <池编号>\n例: /十连awa 1")
            return

        pool_num = int(parts[1])
        pool = self._find_active_pool(pool_num)
        if not pool:
            yield event.plain_result(f"未找到编号为 {pool_num} 的卡池。")
            return

        user_id = event.get_sender_id()
        i, j = self.db.get_counters(user_id)

        ops_6 = [o["name"] for o in pool.get("operators_6", [])]
        ops_5 = [o["name"] for o in pool.get("operators_5", [])]
        pool_type = pool["pool_type_id"]

        # 抽卡（纯计算，不消耗次数，不写入数据库）
        results, new_i, new_j = self.engine.ten_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
        )

        lines = [f"[十连awa·调试] 池{pool_num}「{pool['pool_name']}」"]
        lines.append(f"  模拟计数器: i={i}→{new_i}, j={j}→{new_j}   (未写入)")
        lines.append("")
        for idx, r in enumerate(results, 1):
            star_label = star_mark(r["rarity"])
            up_mark = " [UP]" if r["is_up"] else ""
            lines.append(f"  {idx:2d}. {r['rarity']}★ {r['name']} {star_label}{up_mark}")

        counts = {}
        for r in results:
            counts[r["rarity"]] = counts.get(r["rarity"], 0) + 1
        summary_parts = [f"{s}★x{counts[s]}" for s in [6, 5, 4, 3] if s in counts]
        lines.append(f"  统计: {', '.join(summary_parts)}")

        # 尝试生成图片
        image_path = None
        if self.renderer:
            try:
                image_path = await self.renderer.render_ten_pull(
                    results, pool["pool_name"]
                )
            except Exception as e:
                logger.warning(f"[ArkGacha] 十连awa图片生成失败: {e}")

        if image_path and os.path.isfile(image_path):
            yield event.make_result().message("\n".join(lines)).file_image(image_path)
        else:
            yield event.plain_result("\n".join(lines))

    # ════════════════════════════════════════════════
    #  ========== 管理员调试: 单抽awa ==========
    # ════════════════════════════════════════════════

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("单抽awa")
    async def cmd_debug_single_pull(self, event: AstrMessageEvent):
        """
        管理员调试指令。无视次数限制进行单抽，不记录数据库。
        用法: /单抽awa <池编号>
        """
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            yield event.plain_result("用法: /单抽awa <池编号>\n例: /单抽awa 1")
            return

        pool_num = int(parts[1])
        pool = self._find_active_pool(pool_num)
        if not pool:
            yield event.plain_result(f"未找到编号为 {pool_num} 的卡池。")
            return

        user_id = event.get_sender_id()
        i, j = self.db.get_counters(user_id)

        ops_6 = [o["name"] for o in pool.get("operators_6", [])]
        ops_5 = [o["name"] for o in pool.get("operators_5", [])]
        pool_type = pool["pool_type_id"]

        # 抽卡（纯计算，不消耗次数，不写入数据库）
        result, new_i, new_j = self.engine.single_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
        )

        star_label = star_mark(result["rarity"])
        up_tag = " [UP]" if result["is_up"] else ""
        lines = [
            f"[单抽awa·调试] 池{pool_num}「{pool['pool_name']}」",
            f"  模拟计数器: i={i}→{new_i}, j={j}→{new_j}   (未写入)",
            f"  {result['rarity']}★ {result['name']} {star_label}{up_tag}",
        ]

        # 尝试生成图片
        image_path = None
        if self.renderer:
            try:
                image_path = await self.renderer.render_single_pull(
                    result, pool["pool_name"]
                )
            except Exception as e:
                logger.warning(f"[ArkGacha] 单抽awa图片生成失败: {e}")

        if image_path and os.path.isfile(image_path):
            yield event.make_result().message("\n".join(lines)).file_image(image_path)
        else:
            yield event.plain_result("\n".join(lines))

    # ════════════════════════════════════════════════
    #  ========== 旧指令: /gacha 系列 (已移除) ==========
    # 已合并到 /卡池查询 指令中，不再单独保留
    # ════════════════════════════════════════════════
