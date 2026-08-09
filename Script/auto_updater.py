"""
auto_updater.py - 自动数据更新与后台调度

更新策略:
  1. GitHub SHA256 对比（快速检测官服 gacha_table.json 是否有变）
  2. 有变 → 下载 GitHub 数据 → 跑全量流水线
  3. 无变 → PRTS 降级对比：抓取 PRTS 卡池一览 wikitext，解析后与本地的
     cleaned_pools_final.json 对比 (pool_name, time_start, time_end)
  4. PRTS 有差异 → 跑全量 PRTS 流水线；无差异 → 跳过

用法:
  updater = AutoUpdater(plugin_dir, on_data_updated=callback)
  await updater.start()                   # 启动首次检查 + 定时器
  await updater.stop()                    # 停止定时器
  await updater.check_and_update()        # 手动触发的检查
"""

import asyncio
import hashlib
import os
import subprocess
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional, Set, Tuple
from astrbot.api import logger

# 中国时区（与 pool_generator 保持一致）
CST = timezone(timedelta(hours=8))

GITHUB_RAW_URL = (
    "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/"
    "master/zh_CN/gamedata/excel/gacha_table.json"
)
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT = 60


def _parse_time(t_str: str):
    """解析 'YYYY-MM-DD HH:MM' 格式时间，失败返回 None"""
    if not t_str:
        return None
    try:
        return datetime.strptime(t_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=CST)
    except (ValueError, TypeError):
        return None


class AutoUpdater:
    def __init__(
        self,
        plugin_dir: str,
        on_before_update: Optional[Callable] = None,
        on_after_update: Optional[Callable] = None,
    ):
        self.plugin_dir = plugin_dir
        self.on_before_update = on_before_update
        self.on_after_update = on_after_update

        self.gacha_table_path = os.path.join(plugin_dir, "data", "gacha_table.json")
        self.tools_dir = os.path.join(plugin_dir, "tools")

        self._timer_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_check: float = 0
        self._last_sha256: str = ""

    # ──────────────────── 公共接口 ────────────────────

    async def start(self):
        """启动: 执行首次检查, 然后启动 24h 定时器"""
        logger.info("[AutoUpdater] 启动自动更新检查...")
        self._running = True

        # 首次检查
        await self.check_and_update()

        # 启动定时器
        self._timer_task = asyncio.create_task(self._schedule_loop())
        logger.info(f"[AutoUpdater] 定时器已启动 (间隔 {CHECK_INTERVAL_SECONDS // 3600}h)")

    async def stop(self):
        """停止定时器"""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None
        logger.info("[AutoUpdater] 已停止")

    async def check_and_update(self) -> bool:
        """
        更新策略:
          1. GitHub SHA256 对比（快速）
          2. 相同 → PRTS 降级对比（抓 wikitext → 解析 → 对比本地）
          3. 有差异 → 全量流水线更新
        """
        # ---- Phase 1: GitHub SHA256 ----
        logger.info("[AutoUpdater] [GitHub] 检查 gacha_table.json ...")
        try:
            content = await self._fetch_remote_file()
            if content:
                remote_sha256 = hashlib.sha256(content).hexdigest()
                local_sha256 = self._get_local_sha256()

                if local_sha256 != remote_sha256:
                    logger.info(f"[AutoUpdater] [GitHub] SHA256 差异，执行更新")
                    return await self._perform_github_update(content, remote_sha256)

                logger.info(f"[AutoUpdater] [GitHub] SHA256 一致 ({remote_sha256[:12]})")
            else:
                logger.warning("[AutoUpdater] [GitHub] 远程获取失败")
        except Exception as e:
            logger.error(f"[AutoUpdater] [GitHub] 异常: {e}")

        # ---- Phase 2: PRTS 降级对比 ----
        if not self._has_curl_cffi():
            logger.warning("[AutoUpdater] [PRTS] curl_cffi 未安装，跳过降级")
            self._last_check = time.time()
            return False

        logger.info("[AutoUpdater] [PRTS] 开始降级对比...")
        try:
            if await self._prts_has_updates():
                logger.info("[AutoUpdater] [PRTS] 检测到差异，执行全量更新")
                return await self._run_prts_pipeline()
            else:
                logger.info("[AutoUpdater] [PRTS] 与本地一致，无需更新")
        except Exception as e:
            logger.error(f"[AutoUpdater] [PRTS] 对比异常: {e}")

        self._last_check = time.time()
        return False

    # ──────────────────── PRTS 降级对比 ────────────────────

    @staticmethod
    def _has_curl_cffi() -> bool:
        try:
            import curl_cffi  # noqa
            return True
        except ImportError:
            return False

    async def _prts_has_updates(self) -> bool:
        """
        轻量对比: 抓 PRTS wikitext → 解析 → 对比本地池名/时间。
        返回 True 表示有差异，需要跑全量更新。
        """
        # 1) 抓取 wikitext → data/raw/gacha_wikitext.json
        ok = await self._run_subprocess(
            "fetch_wikitext",
            [sys.executable, os.path.join(self.tools_dir, "fetch_gacha_wikitext.py")],
            cwd=self.tools_dir,
        )
        if not ok:
            return False

        # 2) 解析 wikitext → data/processed/cleaned_pools.json
        ok = await self._run_subprocess(
            "clean_pools",
            [sys.executable, os.path.join(self.tools_dir, "clean_gacha_pools.py")],
            cwd=self.tools_dir,
        )
        if not ok:
            return False

        # 3) 对比
        prts_path = os.path.join(self.plugin_dir, "data", "processed", "cleaned_pools.json")
        local_path = os.path.join(self.plugin_dir, "data", "processed", "cleaned_pools_final.json")

        if not os.path.isfile(prts_path):
            return False
        if not os.path.isfile(local_path):
            logger.info("[AutoUpdater] [PRTS] 本地无数据，视为有新数据")
            return True

        with open(prts_path, "r", encoding="utf-8") as f:
            prts_pools = json.load(f)
        with open(local_path, "r", encoding="utf-8") as f:
            local_pools = json.load(f)

        def _is_active(p) -> bool:
            """判断池子当前是否进行中 (time_start <= now <= time_end)"""
            start = _parse_time(p.get("time_start", ""))
            end = _parse_time(p.get("time_end", ""))
            if not start or not end:
                return False
            now = datetime.now(CST)
            return start <= now <= end

        # 只对比"进行中"的池子，避免历史已结束池子的微小差异引发无谓的全量更新
        prts_active = [p for p in prts_pools if _is_active(p)]
        local_active = [p for p in local_pools if _is_active(p)]

        def key(p):
            return (p.get("pool_name", ""), p.get("time_start", ""), p.get("time_end", ""))

        prts_set: Set[Tuple] = {key(p) for p in prts_active}
        local_set: Set[Tuple] = {key(p) for p in local_active}

        added = prts_set - local_set
        removed = local_set - prts_set

        if not added and not removed:
            logger.info(f"[AutoUpdater] [PRTS] 一致 ({len(local_active)} 个进行中池)")
            return False

        if added:
            logger.info(f"[AutoUpdater] [PRTS] PRTS 新增 {len(added)} 个池:")
            for k in sorted(added)[:5]:
                logger.info(f"    + {k[0]} ({k[1]} ~ {k[2]})")
        if removed:
            logger.info(f"[AutoUpdater] [PRTS] PRTS 移除 {len(removed)} 个池:")
            for k in sorted(removed)[:5]:
                logger.info(f"    - {k[0]} ({k[1]} ~ {k[2]})")
        return True

    # ──────────────────── PRTS 全量流水线 ────────────────────

    async def _run_prts_pipeline(self) -> bool:
        """PRTS 全量更新: update_all.py + pool_generator.py"""
        logger.info("[AutoUpdater] [PRTS] 全量更新流水线...")
        if self.on_before_update:
            try:
                cb = self.on_before_update
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception as e:
                logger.info(f"[AutoUpdater] on_before_update 异常: {e}")

        ok = await self._run_update_pipeline()
        gen_ok = await self._run_pool_generator() if ok else False

        if not ok or not gen_ok:
            return False

        if self.on_after_update:
            try:
                cb = self.on_after_update
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception as e:
                logger.error(f"[AutoUpdater] on_after_update 异常: {e}")

        self._last_check = time.time()
        logger.info("[AutoUpdater] [PRTS] 全量更新完成!")
        return True

    # ──────────────────── GitHub 更新 ────────────────────

    async def _fetch_remote_file(self) -> Optional[bytes]:
        import aiohttp
        try:
            timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(GITHUB_RAW_URL) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.info(f"[AutoUpdater] HTTP {resp.status}")
                    return None
        except aiohttp.ClientError as e:
            logger.warning(f"[AutoUpdater] HTTP 失败: {e}")
            return None
        except ImportError:
            logger.warning("[AutoUpdater] aiohttp 未安装")
            return None

    def _get_local_sha256(self) -> str:
        if not os.path.isfile(self.gacha_table_path):
            return ""
        try:
            with open(self.gacha_table_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"[AutoUpdater] 读取本地文件失败: {e}")
            return ""

    async def _perform_github_update(self, content: bytes, new_sha256: str) -> bool:
        logger.info("[AutoUpdater] [GitHub] 执行更新...")
        try:
            os.makedirs(os.path.dirname(self.gacha_table_path), exist_ok=True)
            with open(self.gacha_table_path, "wb") as f:
                f.write(content)
        except Exception as e:
            logger.error(f"[AutoUpdater] 保存失败: {e}")
            return False

        if self.on_before_update:
            try:
                cb = self.on_before_update
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception as e:
                logger.error(f"[AutoUpdater] on_before_update 异常: {e}")

        ok = await self._run_update_pipeline()
        gen_ok = await self._run_pool_generator() if ok else False
        if not ok or not gen_ok:
            return False

        if self.on_after_update:
            try:
                cb = self.on_after_update
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception as e:
                logger.error(f"[AutoUpdater] on_after_update 异常: {e}")

        self._last_check = time.time()
        self._last_sha256 = new_sha256
        logger.info("[AutoUpdater] [GitHub] 更新完成!")
        return True

    # ──────────────────── 子进程执行 ────────────────────

    async def _run_update_pipeline(self) -> bool:
        """在子进程中运行 tools/update_all.py"""
        update_script = os.path.join(self.tools_dir, "update_all.py")
        return await self._run_subprocess(
            "update_all.py",
            [sys.executable, update_script],
            cwd=self.tools_dir,
        )

    async def _run_pool_generator(self) -> bool:
        """在子进程中运行 Script/pool_generator.py"""
        script_dir = os.path.join(self.plugin_dir, "Script")
        gen_script = os.path.join(script_dir, "pool_generator.py")
        return await self._run_subprocess(
            "pool_generator.py",
            [sys.executable, gen_script],
            cwd=script_dir,
        )

    async def _run_subprocess(self, name: str, cmd: list, cwd: str) -> bool:
        """在独立线程中运行子进程，不阻塞事件循环"""
        loop = asyncio.get_event_loop()

        def _run():
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if proc.returncode != 0:
                    logger.error(f"[AutoUpdater] [{name}] 失败 (exit {proc.returncode})")
                    if proc.stderr:
                        logger.info(f"  stderr: {proc.stderr[:500]}")
                    return False
                logger.info(f"[AutoUpdater] [{name}] 完成")
                return True
            except subprocess.TimeoutExpired:
                logger.error(f"[AutoUpdater] [{name}] 超时 (5分钟)")
                return False
            except Exception as e:
                logger.error(f"[AutoUpdater] [{name}] 异常: {e}")
                return False

        logger.info(f"[AutoUpdater] 正在运行 {name}...")
        return await loop.run_in_executor(None, _run)

    # ──────────────────── 定时器 ────────────────────

    async def _schedule_loop(self):
        """后台 24h 循环"""
        logger.info(f"[AutoUpdater] 后台定时器运行中 (下次检查: {CHECK_INTERVAL_SECONDS // 3600}h 后)")
        while self._running:
            try:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                if self._running:
                    logger.info("[AutoUpdater] 定时检查触发...")
                    await self.check_and_update()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AutoUpdater] 定时器异常: {e}")
                await asyncio.sleep(60)

    # ──────────────────── 状态查询 ────────────────────

    def get_status(self) -> dict:
        """获取更新器状态"""
        return {
            "running": self._running,
            "last_check": self._last_check,
            "last_sha256": self._last_sha256[:16] + "..." if self._last_sha256 else "",
            "gacha_table_exists": os.path.isfile(self.gacha_table_path),
            "curl_cffi_available": self._has_curl_cffi(),
        }
