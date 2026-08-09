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
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig, logger

# 中国时区
CST = timezone(timedelta(hours=8))

# 插件目录
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(PLUGIN_DIR, "Script")
for p in [PLUGIN_DIR, SCRIPT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 卡池封面图 URL 缓存 (30 天 TTL)
CACHE_TTL_DAYS = 30
POOL_CACHE_FILE = os.path.join(PLUGIN_DIR, "data", "cache", "pool_images.json")

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

        # 数据
        self.pools: List[Dict] = []
        self.active_pools: List[Dict] = []
        self.base_pools: Dict = {}

        # 模块
        self.engine = None
        self.db = None
        self.updater = None
        self.renderer = None  # 图片渲染器

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

            # 4. 初始化抽卡引擎
            self._init_engine()

            # 5. 初始化图片渲染器
            await self._init_renderer()

            # 6. 启动自动更新
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
            os.path.join(PLUGIN_DIR, "data", "processed"),
        ]
        path = _find_file("cleaned_pools_final.json", candidates)
        if not path:
            logger.info(
                "[ArkGacha] 未找到 cleaned_pools_final.json，等待自动更新器首次拉取生成卡池数据"
            )
            self.pools = []
            return
        with open(path, "r", encoding="utf-8") as f:
            self.pools = json.load(f)
        logger.info(f"[ArkGacha] 已加载 {len(self.pools)} 个卡池")
        logger.info(f"[ArkGacha] 已加载 {len(self.pools)} 个卡池数据")

    def _load_active_pools(self):
        """加载/重新生成 active_pools.json"""
        active_path = os.path.join(PLUGIN_DIR, "data", "processed", "active_pools.json")

        # 尝试重新生成（对比当前时间）
        try:
            from pool_generator import generate_active_pools
            pools_path = _find_file("cleaned_pools_final.json", [
                os.path.join(PLUGIN_DIR, "data", "processed"),
            ])
            if pools_path:
                active_data = generate_active_pools(pools_path)
                os.makedirs(os.path.dirname(active_path), exist_ok=True)
                with open(active_path, "w", encoding="utf-8") as f:
                    json.dump(active_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[ArkGacha] 已生成 active_pools.json ({len(active_data)} 个进行中)")
        except Exception as e:
            logger.warning(f"[ArkGacha] 重新生成 active_pools 失败: {e}, 尝试读取已有文件")

        # 读取
        if os.path.isfile(active_path):
            with open(active_path, "r", encoding="utf-8") as f:
                self.active_pools = json.load(f)
        else:
            self.active_pools = []

    def _init_database(self):
        """初始化 SQLite 数据库（存放于 AstrBot/data/ 目录）"""
        try:
            from db_manager import DBManager

            # AstrBot 项目级 data/ 目录
            astrbot_data = os.path.join(PLUGIN_DIR, "..", "..")
            db_dir = os.path.abspath(astrbot_data) if os.path.isdir(os.path.abspath(astrbot_data)) else os.path.join(PLUGIN_DIR, "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "user.db")

            self.db = DBManager(db_path)
            logger.info(f"[ArkGacha] 数据库已初始化 ({db_path})")
        except Exception as e:
            logger.error(f"[ArkGacha] 数据库初始化失败: {e}")
            self.db = None

    def _init_engine(self):
        """初始化抽卡概率引擎"""
        bp_path = os.path.join(PLUGIN_DIR, "data", "processed", "base_pools.json")
        rules_path = os.path.join(PLUGIN_DIR, "data", "processed", "pool_rules.json")

        if not os.path.isfile(bp_path) or not os.path.isfile(rules_path):
            # 尝试自动生成
            try:
                import subprocess, sys
                gen_path = os.path.join(SCRIPT_DIR, "pool_generator.py")
                subprocess.run(
                    [sys.executable, gen_path, "--base-only"],
                    cwd=SCRIPT_DIR, capture_output=True, timeout=60,
                )
                logger.info("[ArkGacha] 自动生成 base_pools.json")
            except Exception as e:
                logger.warning(f"[ArkGacha] 自动生成 base_pools 失败: {e}")

        try:
            from gacha_engine import GachaEngine
            self.engine = GachaEngine(bp_path, rules_path)
            logger.info("[ArkGacha] 抽卡引擎已初始化")
        except Exception as e:
            logger.error(f"[ArkGacha] 引擎初始化失败: {e}")
            self.engine = None

    async def _init_renderer(self):
        """初始化图片渲染器"""
        try:
            from image_renderer import ImageRenderer
            self.renderer = ImageRenderer(PLUGIN_DIR)
            await self.renderer.initialize()
            logger.info("[ArkGacha] 图片渲染器已初始化")
        except Exception as e:
            logger.warning(f"[ArkGacha] 图片渲染器初始化失败（图片功能不可用）: {e}")
            self.renderer = None

    def _start_updater(self):
        """启动自动更新器"""
        try:
            from auto_updater import AutoUpdater

            async def on_after_update():
                """数据更新后的回调：重新加载所有数据"""
                logger.info("[ArkGacha] 数据已更新，重新加载...")
                self._load_pool_data()
                self._load_active_pools()
                self._init_engine()

            self.updater = AutoUpdater(
                PLUGIN_DIR,
                on_after_update=on_after_update,
            )

            # 在事件循环中启动
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.updater.start())
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
    def _save_pool_cache(cls, pool_name: str, url: str):
        """写入/更新 pool_images.json 缓存，同时清理超期条目"""
        try:
            os.makedirs(os.path.dirname(POOL_CACHE_FILE), exist_ok=True)
            data = cls._load_pool_cache()
            data[pool_name] = {
                "url": url,
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
                data.pop(k, None)
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

    def _check_loaded(self) -> Optional[str]:
        """返回错误信息或 None"""
        if not self._loaded:
            return "插件数据未加载，请稍后再试。"
        if not self.active_pools:
            return "当前没有进行中的卡池，无法抽卡。"
        if not self.engine:
            return "抽卡引擎未就绪。"
        if not self.db:
            return "数据库未就绪。"
        return None

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

        # 抽卡
        result, new_i, new_j = self.engine.single_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
            owned_characters=None,
        )

        # 首发十连五星保底: 累计第10抽 且 前10抽从未出≥5★ 且 本抽<5★ → 强制替换为5★
        if self.db.check_first_ten_trigger(user_id, pool["active_id"], result["rarity"]):
            result, new_i, new_j = self.engine.single_pull(
                pool_type, ops_6, ops_5, i, j,
                select_rules=pool.get("select_rules"),
                owned_characters=None,
                force_rarity=5,
            )

        # 更新数据库
        self.db.update_counters(user_id, new_i, new_j, draw_consumed=1)
        self.db.add_character(user_id, result["name"], result["rarity"])
        self.db.increment_pull_count(user_id, pool["active_id"], result["rarity"])

        # 格式化输出
        star_label = star_mark(result["rarity"])
        up_tag = " [UP]" if result["is_up"] else ""

        text = (
            f"[单抽结果] 池{pool_num}「{pool['pool_name']}」\n"
            f"{result['rarity']}★ {result['name']} {star_label}{up_tag}"
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

        # 十连 (引擎内处理首发十连五星保底: 全局第10抽若<5★则强制替换为5★)
        results, new_i, new_j = self.engine.ten_pull(
            pool_type, ops_6, ops_5, i, j,
            select_rules=pool.get("select_rules"),
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
            if urls:
                # 逐个尝试直到找到可达的 URL（带 30 天缓存）
                valid_url = await self._find_valid_url(urls, name)
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
    #  ========== 管理员调试: 抽卡awa ==========
    # ════════════════════════════════════════════════

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("抽卡awa")
    async def cmd_debug_ten_pull(self, event: AstrMessageEvent):
        """
        管理员调试指令。无视次数限制进行十连，不记录数据库。
        用法: /抽卡awa <池编号>
        """
        err = self._check_loaded()
        if err:
            yield event.plain_result(err)
            return

        parts = event.message_str.strip().split()
        if len(parts) < 2 or not parts[1].isdigit():
            yield event.plain_result("用法: /抽卡awa <池编号>\n例: /抽卡awa 1")
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

        lines = [f"[抽卡awa·调试] 池{pool_num}「{pool['pool_name']}」"]
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
                logger.warning(f"[ArkGacha] 抽卡awa图片生成失败: {e}")

        if image_path and os.path.isfile(image_path):
            yield event.make_result().message("\n".join(lines)).file_image(image_path)
        else:
            yield event.plain_result("\n".join(lines))

    # ════════════════════════════════════════════════
    #  ========== 旧指令: /gacha 系列 (已移除) ==========
    # 已合并到 /卡池查询 指令中，不再单独保留
    # ════════════════════════════════════════════════
