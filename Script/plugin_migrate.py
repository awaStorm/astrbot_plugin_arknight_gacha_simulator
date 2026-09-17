# -*- coding: utf-8 -*-
"""
plugin_migrate.py - 旧版本数据目录的一次性兼容迁移

背景
    旧版本把运行时数据写在【插件安装目录】下的 data/ 中。这不符合 AstrBot 规范：
    插件安装目录属于只读资源区，插件更新 / 重装会整体覆盖它，用户数据会随之丢失。
    新版本改为统一写入框架分配的插件专属数据目录：
        data/plugin_data/<插件名>/

本模块的作用
    在插件初始化时做一次兼容处理：若发现【本插件自己的】旧数据目录仍然存在，
    且新的插件专属目录尚未建立，就把它整体迁移过去，使老用户升级后不会丢失
    抽卡次数、签到记录与潜能仓库。

访问范围（重要）
    本模块只涉及两个目录，二者都与本插件直接相关，不读取、不遍历任何其它位置：

      · 源目录  ：本插件安装目录下的 data/   —— 即 <本文件所在目录>/../data
      · 目标目录：框架通过 StarTools.get_data_dir() 分配给本插件的专属数据目录

    不通过相对路径向上跨越到插件的上级目录，也不访问 AstrBot 的其它路径。
"""
import os
import shutil

from astrbot.api import logger
from astrbot.api.star import StarTools

# 插件唯一标识（与 main.py 保持一致）
PLUGIN_NAME = "astrbot_plugin_arknight_gacha_simulator"

# 本插件的安装目录：本文件位于 <插件根>/Script/，其上一级即插件根
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 旧版本使用的数据目录：插件安装目录下的 data/
LEGACY_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")


def _is_empty_dir(path: str) -> bool:
    """目录存在且为空时返回 True"""
    try:
        return not os.listdir(path)
    except OSError:
        return False


def migrate_legacy_data(plugin_data_dir: str) -> bool:
    """
    将旧版本遗留在插件安装目录下的 data/ 迁移到插件专属数据目录。

    仅在下列条件全部满足时才执行迁移，以免误删或误覆盖用户数据：
      · 旧目录存在；
      · 旧目录与新目录不是同一个位置；
      · 新目录不存在，或存在但为空。

    迁移使用 shutil.move：同一磁盘分区上是改名（瞬间完成），跨分区则为
    复制后删除。任何异常都只告警，绝不影响插件启动。

    返回是否实际执行了迁移。
    """
    legacy = os.path.abspath(LEGACY_DATA_DIR)
    target = os.path.abspath(plugin_data_dir)

    # 位置相同则无需迁移（同时避免把自己移到自己里）
    if legacy == target:
        return False
    # 没有旧数据可迁
    if not os.path.isdir(legacy):
        return False
    # 新目录已有内容，说明已经迁移过或用户已在使用，保持现状
    if os.path.isdir(target) and not _is_empty_dir(target):
        return False

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # 目标若为空目录，先移除，便于 move 直接落位
        if os.path.isdir(target):
            os.rmdir(target)
        shutil.move(legacy, target)
        logger.info(f"[ArkGacha] 检测到旧版本数据，已迁移到: {target}")
        return True
    except Exception as e:
        logger.warning(
            f"[ArkGacha] 旧数据目录迁移未完成（不影响插件使用）: {e}")
        return False


def _astrbot_data_root(plugin_data_dir: str) -> str:
    """
    由框架分配的插件专属目录反推 AstrBot 的数据根目录：

        <data>/plugin_data/<插件名>   →   <data>

    这里用的是框架 API 返回的绝对路径，而不是通过相对路径跨越插件目录向上计算。
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(plugin_data_dir)))


def migrate_legacy_database(plugin_data_dir: str) -> bool:
    """
    迁移旧版本遗留在 AstrBot 数据根目录下的 SQLite 数据库。

    背景
        旧版本把数据库写在 <AstrBot>/data/user.db。为兼容老用户，
        这里做一次【受限的一次性迁移】：只针对唯一确定的那几个文件
        （user.db 及其 SQLite 可能产生的 -wal / -shm 伴生文件），
        不遍历目录、不读取或修改该位置下的任何其它内容。

    仅在下列条件全部满足时才动作：
        · 旧数据库文件存在；
        · 本插件在新位置尚无数据库（避免覆盖用户正在使用的数据）。

    返回是否实际执行了迁移。
    """
    target_dir = os.path.abspath(plugin_data_dir)
    legacy_dir = _astrbot_data_root(target_dir)

    # 二者位置相同（例如本地调试模式下），无需迁移
    if legacy_dir == target_dir:
        return False

    target_db = os.path.join(target_dir, "user.db")
    if os.path.isfile(target_db):
        # 新位置已有数据库，保持现状，不动用户数据
        return False

    # SQLite 在 WAL 模式下会生成 -wal / -shm 伴生文件，需一并迁移
    suffixes = ("", "-wal", "-shm")
    present = [s for s in suffixes
               if os.path.isfile(os.path.join(legacy_dir, "user.db" + s))]
    if not present:
        return False

    try:
        os.makedirs(target_dir, exist_ok=True)
        for s in present:
            shutil.move(os.path.join(legacy_dir, "user.db" + s),
                        os.path.join(target_dir, "user.db" + s))
        logger.info(f"[ArkGacha] 已迁移旧版本数据库到: {target_db}")
        return True
    except Exception as e:
        logger.warning(f"[ArkGacha] 旧版本数据库迁移未完成（不影响使用）: {e}")
        return False


def ensure_migrated() -> bool:
    """
    对外入口：按框架分配的插件专属目录做一次旧数据迁移。

    由插件入口 main.py 在初始化时调用；重复调用是安全的
    （目标已存在时会直接跳过）。

    依次处理两处旧位置：
        1. 插件安装目录下的 data/       —— 缓存 / 抓取数据 / 字体
        2. AstrBot 数据根目录下的 user.db —— 旧版本数据库
    """
    try:
        target = str(StarTools.get_data_dir(PLUGIN_NAME))
    except Exception as e:
        logger.warning(f"[ArkGacha] 获取插件数据目录失败，跳过迁移检查: {e}")
        return False

    moved_data = migrate_legacy_data(target)
    moved_db = migrate_legacy_database(target)
    return moved_data or moved_db
