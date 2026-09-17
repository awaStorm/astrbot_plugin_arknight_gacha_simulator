# -*- coding: utf-8 -*-
"""
font_manager.py - 字体资源管理

职责
    确保插件运行所需的字体已就绪。字体【不随插件包分发】，而是在首次需要时
    从官方来源下载并缓存到 data/fonts/（该目录已被 .gitignore 排除），
    以此控制插件包体积（AstrBot 插件市场限制单包 ≤ 16MB）。

当前字体
    HarmonyOS Sans SC Bold
      · 来源：OpenHarmony 官方仓库 openharmony/utils_system_resources
              （URL 钉死到固定 commit，内容不可变）
      · 许可：HarmonyOS Sans Fonts License Agreement
      · 详见仓库根目录的 THIRD_PARTY_NOTICES.md

设计约束
    · 只在【缺失或校验失败】时下载；已缓存且校验通过则零请求；
    · 下载后做 SHA-256 校验，不匹配直接丢弃，绝不落盘不可信文件；
    · 落盘用 .part + os.replace 原子替换，避免半截文件被当成有效缓存；
    · 任何环节失败都只告警、不抛异常 —— 字体缺失时文字渲染静默降级，
      绝不能因此阻断插件启动。
"""
import asyncio
import hashlib
import os

from astrbot.api import logger

import composer_config as cfg

# ---------------------------------------------------------------------------
#  字体清单
# ---------------------------------------------------------------------------
# URL 固定到 commit，保证内容永久稳定；若将来需要升级字体，
# 同时更新 url 中的 commit 与 sha256 即可。
_HARMONYOS_COMMIT = "15ada4f9385a68ec18e2357c43dae158da723f39"

FONT_SOURCES = (
    {
        "name": "HarmonyOS Sans SC Bold",
        "filename": "HarmonyOS_Sans_SC_Bold.ttf",
        "url": (
            "https://raw.githubusercontent.com/openharmony/utils_system_resources/"
            f"{_HARMONYOS_COMMIT}/fonts/HarmonyOS_Sans_SC_Bold.ttf"
        ),
        # 实测自 OpenHarmony 官方仓库（2023-12-21 commit，8327680 字节）
        "sha256": "705136d8e45591b6451da444f1c926b12b77536158f0bff744529b87010df3ee",
        "size": 8327680,
    },
)

DOWNLOAD_TIMEOUT = 180  # 秒。字体约 8MB，慢网络下需要留足时间

# 需要随字体一并保留在缓存目录中的协议文件。
# 协议要求：任何字体副本中都必须保留版权声明与协议原文。
NOTICE_FILES = (
    "LICENSE_HarmonyOS_Sans.txt",
    "LICENSE_SourceHanSans.txt",
)


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    """计算文件 SHA-256；读取失败返回空串"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


async def _download(url: str):
    """下载字节流，失败返回 None"""
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"[ArkGacha] 字体下载返回 HTTP {resp.status}: {url}")
                    return None
                return await resp.read()
    except Exception as e:
        logger.warning(f"[ArkGacha] 字体下载异常: {e}")
        return None


async def _ensure_one(spec: dict) -> bool:
    """确保单个字体就绪，返回是否可用"""
    name = spec["name"]
    filename = spec["filename"]
    local = os.path.join(cfg.FONT_DIR, filename)

    # 1) 运行时缓存命中且校验通过 —— 零网络请求
    if os.path.isfile(local):
        if _sha256_file(local) == spec["sha256"]:
            return True
        logger.warning(f"[ArkGacha] 字体 {name} 缓存校验不一致，将重新下载")
        try:
            os.remove(local)
        except OSError:
            pass

    # 2) 使用者手动放置的字体视为可信，跳过下载
    manual = os.path.join(cfg.FALLBACK_FONT_DIR, filename)
    if os.path.isfile(manual):
        logger.info(f"[ArkGacha] 使用手动放置的字体: {manual}")
        return True

    # 3) 首次运行：从官方源下载
    logger.info(f"[ArkGacha] 首次运行，正在下载字体 {name} …")
    data = await _download(spec["url"])
    if not data:
        logger.warning(f"[ArkGacha] 字体 {name} 下载失败（下载源不可达）")
        return False

    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        logger.warning(
            f"[ArkGacha] 字体 {name} SHA-256 校验不通过，已丢弃："
            f"期望 {spec['sha256'][:16]}…，实际 {digest[:16]}…")
        return False

    try:
        os.makedirs(cfg.FONT_DIR, exist_ok=True)
        tmp = local + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, local)  # 原子替换，避免半截文件被当成有效缓存
    except OSError as e:
        logger.warning(f"[ArkGacha] 字体 {name} 写入失败: {e}")
        return False

    logger.info(
        f"[ArkGacha] 字体 {name} 已就绪（{len(data) / 1024 / 1024:.1f} MB）")
    return True


async def ensure_fonts() -> int:
    """
    确保全部字体现已就绪，返回成功就绪的数量。

    仅应在插件初始化时调用一次；内部已做"存在即跳过"判断，
    重复调用不会产生额外下载。
    """
    if not FONT_SOURCES:
        return 0

    try:
        os.makedirs(cfg.FONT_DIR, exist_ok=True)
    except OSError as e:
        logger.warning(f"[ArkGacha] 字体目录创建失败: {e}")
        return 0

    ready = 0
    for spec in FONT_SOURCES:
        try:
            if await _ensure_one(spec):
                ready += 1
        except Exception as e:
            # 单个字体失败不影响其它字体，也不影响插件启动
            logger.warning(f"[ArkGacha] 字体 {spec.get('name')} 准备失败: {e}")

    if ready < len(FONT_SOURCES):
        logger.warning(
            f"[ArkGacha] 字体就绪 {ready}/{len(FONT_SOURCES)}。"
            "缺失时抽卡结果图不会绘制文字（其余功能不受影响）；"
            f"可将字体手动放入 {cfg.FALLBACK_FONT_DIR} 后重载插件。")

    # 字体副本旁保留授权协议文本
    _sync_notice_files()
    return ready


def _sync_notice_files():
    """
    把仓库内的字体协议文件复制到字体缓存目录。

    许可协议要求"任何字体副本中须保留版权声明与本协议"，
    因此字体下载到 data/fonts/ 后，对应协议文本也要一并存在。
    """
    import shutil
    for fn in NOTICE_FILES:
        src = os.path.join(cfg.FALLBACK_FONT_DIR, fn)
        dst = os.path.join(cfg.FONT_DIR, fn)
        if os.path.isfile(src) and not os.path.isfile(dst):
            try:
                shutil.copyfile(src, dst)
            except OSError:
                pass


def font_ready(filename: str) -> bool:
    """指定字体是否可用（运行时缓存或手动放置）"""
    return (os.path.isfile(os.path.join(cfg.FONT_DIR, filename))
            or os.path.isfile(os.path.join(cfg.FALLBACK_FONT_DIR, filename)))


if __name__ == "__main__":  # 手动触发下载（便于排查网络问题）
    print("就绪字体数:", asyncio.run(ensure_fonts()))
