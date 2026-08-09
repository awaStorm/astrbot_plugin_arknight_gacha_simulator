"""
db_manager.py - SQLite 用户数据库管理

职责:
  - 创建/管理 user.db (用户表 + 干员持有表)
  - 提供 CRUD 操作: 签到、保底计数器、潜能累加、查询

用法:
  from db_manager import DBManager
  db = DBManager("path/to/user.db")  # 建议指向项目级 data/ 目录
  db.do_sign_in("12345")
  db.update_counters("12345", i=5, j=3)
  db.add_character("12345", "酒神", 6)
"""

import os
import sqlite3
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple


class DBManager:
    def __init__(self, db_path: str = "data/user.db"):
        """
        db_path: SQLite 数据库文件的完整路径，或相对于调用方的路径。
        根据 AstrBot 规范，持久化数据应存储于项目级 data/ 目录而非插件目录内，
        防止插件更新/重装时数据被覆盖。
        """
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ──────────────────── 初始化 ────────────────────

    def _init_db(self):
        """建表"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id          TEXT PRIMARY KEY,
                    draw_count       INTEGER DEFAULT 0,
                    last_sign_date   TEXT,
                    six_star_counter INTEGER DEFAULT 0,
                    five_star_counter INTEGER DEFAULT 0,
                    total_pulls      INTEGER DEFAULT 0,
                    created_at       TEXT DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS owned_characters (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       TEXT NOT NULL,
                    char_name     TEXT NOT NULL,
                    rarity        INTEGER NOT NULL,
                    count         INTEGER DEFAULT 1,
                    first_obtained TEXT,
                    last_obtained  TEXT,
                    UNIQUE(user_id, char_name),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS user_pool_first_pull (
                    user_id              TEXT NOT NULL,
                    pool_id              INTEGER NOT NULL,
                    pull_count           INTEGER DEFAULT 0,
                    has_seen_5star_above INTEGER DEFAULT 0,
                    updated_at           TEXT,
                    PRIMARY KEY (user_id, pool_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_owned_user
                    ON owned_characters(user_id);
                CREATE INDEX IF NOT EXISTS idx_owned_rarity
                    ON owned_characters(user_id, rarity);
            """)

            self._migrate_first_pull_table()

    def _migrate_first_pull_table(self):
        """
        旧版 user_pool_first_pull 表使用 has_done 字段（十连命令级保底）。
        迁移为 pull_count + has_seen_5star_above：
          - has_done=1 表示旧版已走过首发十连流程 → seen=1（不再触发保底）
          - 旧记录无法还原精确 pull_count，保守置为 10（超出触发窗口）
        """
        try:
            with self._get_conn() as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(user_pool_first_pull)").fetchall()]
                if "has_done" in cols and "pull_count" not in cols:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    # 迁移前确保 users 表存在对应用户记录，避免外键约束导致迁移失败
                    conn.execute(
                        "INSERT OR IGNORE INTO users (user_id) "
                        "SELECT DISTINCT user_id FROM user_pool_first_pull"
                    )
                    conn.executescript(f"""
                        ALTER TABLE user_pool_first_pull RENAME TO user_pool_first_pull_old;
                        CREATE TABLE user_pool_first_pull (
                            user_id              TEXT NOT NULL,
                            pool_id              INTEGER NOT NULL,
                            pull_count           INTEGER DEFAULT 0,
                            has_seen_5star_above INTEGER DEFAULT 0,
                            updated_at           TEXT,
                            PRIMARY KEY (user_id, pool_id),
                            FOREIGN KEY(user_id) REFERENCES users(user_id)
                        );
                        INSERT INTO user_pool_first_pull
                            (user_id, pool_id, pull_count, has_seen_5star_above, updated_at)
                        SELECT user_id, pool_id, 10, has_done, '{now}' FROM user_pool_first_pull_old;
                        DROP TABLE user_pool_first_pull_old;
                    """)
                    conn.commit()
                    logger = None
                    try:
                        from astrbot.api import logger
                    except ImportError:
                        pass
                    if logger:
                        logger.info("[ArkGacha] user_pool_first_pull 表已从 has_done 迁移到 pull_count 结构")
        except Exception:
            # 迁移失败不影响主流程，忽略
            pass

    # ──────────────────── 用户 CRUD ────────────────────

    def get_or_create_user(self, user_id: str) -> dict:
        """获取或创建用户，返回用户数据字典"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO users (user_id, created_at) VALUES (?, ?)",
                    (user_id, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
            return dict(row)

    def get_draw_count(self, user_id: str) -> int:
        """获取用户剩余抽卡次数"""
        user = self.get_or_create_user(user_id)
        return user.get("draw_count", 0)

    def consume_draw(self, user_id: str, amount: int = 1) -> bool:
        """消耗抽卡次数，返回是否成功"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT draw_count FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None or row["draw_count"] < amount:
                return False
            conn.execute(
                "UPDATE users SET draw_count = draw_count - ? WHERE user_id = ?",
                (amount, user_id),
            )
            conn.commit()
            return True

    # ──────────────────── 签到 ────────────────────

    def check_sign_in(self, user_id: str) -> bool:
        """检查今天是否已签到"""
        today = date.today().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT last_sign_date FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return row is not None and row["last_sign_date"] == today

    def do_sign_in(self, user_id: str, amount: int = 10) -> Tuple[bool, int]:
        """
        执行签到。返回 (是否成功, 当前剩余次数)
        - 已签到 → (False, 当前次数)
        - 签到成功 → (True, 签到后次数)
        """
        today = date.today().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT draw_count, last_sign_date FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if row is None:
                # 新用户，创建并签到
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO users (user_id, draw_count, last_sign_date, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, amount, today, now),
                )
                conn.commit()
                return True, amount

            if row["last_sign_date"] == today:
                # 已签到
                return False, row["draw_count"]

            conn.execute(
                "UPDATE users SET draw_count = draw_count + ?, last_sign_date = ? "
                "WHERE user_id = ?",
                (amount, today, user_id),
            )
            conn.commit()
            return True, row["draw_count"] + amount

    # ──────────────────── 保底计数器 ────────────────────

    def get_counters(self, user_id: str) -> Tuple[int, int]:
        """返回 (six_star_counter, five_star_counter)"""
        user = self.get_or_create_user(user_id)
        return user.get("six_star_counter", 0), user.get("five_star_counter", 0)

    def update_counters(self, user_id: str, i: int, j: int, draw_consumed: int = 1):
        """
        更新保底计数器并累计总抽数。
        i: 六星计数器 (新值), j: 五星计数器 (新值)
        """
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE users
                   SET six_star_counter = ?,
                       five_star_counter = ?,
                       total_pulls = total_pulls + ?,
                       draw_count = CASE WHEN draw_count >= ? THEN draw_count - ? ELSE draw_count END
                   WHERE user_id = ?""",
                (i, j, draw_consumed, draw_consumed, draw_consumed, user_id),
            )
            conn.commit()

    # ──────────────────── 干员持有 ────────────────────

    def add_character(self, user_id: str, char_name: str, rarity: int):
        """
        添加干员到持有列表，已存在则 count+1。
        首次获得自动记录日期。
        """
        today = date.today().isoformat()
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, count FROM owned_characters WHERE user_id = ? AND char_name = ?",
                (user_id, char_name),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE owned_characters SET count = count + 1, last_obtained = ? "
                    "WHERE id = ?",
                    (today, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO owned_characters
                       (user_id, char_name, rarity, count, first_obtained, last_obtained)
                       VALUES (?, ?, ?, 1, ?, ?)""",
                    (user_id, char_name, rarity, today, today),
                )
            conn.commit()

    def get_user_characters(self, user_id: str, rarity_filter: Optional[int] = None) -> List[dict]:
        """
        获取用户持有干员列表。
        返回 [{char_name, rarity, count, first_obtained, last_obtained}, ...]
        按稀有度降序、获得的次数降序排列。
        """
        with self._get_conn() as conn:
            if rarity_filter is not None:
                rows = conn.execute(
                    """SELECT char_name, rarity, count, first_obtained, last_obtained
                       FROM owned_characters
                       WHERE user_id = ? AND rarity = ?
                       ORDER BY rarity DESC, count DESC""",
                    (user_id, rarity_filter),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT char_name, rarity, count, first_obtained, last_obtained
                       FROM owned_characters
                       WHERE user_id = ?
                       ORDER BY rarity DESC, count DESC""",
                    (user_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_total_pulls(self, user_id: str) -> int:
        """获取用户历史总抽数"""
        user = self.get_or_create_user(user_id)
        return user.get("total_pulls", 0)

    def get_user_stats(self, user_id: str) -> dict:
        """
        获取用户统计摘要
        """
        user = self.get_or_create_user(user_id)
        chars = self.get_user_characters(user_id)

        by_rarity = {}
        for c in chars:
            r = c["rarity"]
            if r not in by_rarity:
                by_rarity[r] = {"unique": 0, "total": 0}
            by_rarity[r]["unique"] += 1
            by_rarity[r]["total"] += c["count"]

        return {
            "user_id": user_id,
            "draw_count": user.get("draw_count", 0),
            "total_pulls": user.get("total_pulls", 0),
            "six_star_counter": user.get("six_star_counter", 0),
            "last_sign_date": user.get("last_sign_date", ""),
            "owned_unique": len(chars),
            "owned_total": sum(c["count"] for c in chars),
            "by_rarity": by_rarity,
        }

    # ──────────────────── 首发十连保底跟踪（计数器级） ────────────────────

    def _ensure_first_pull_record(self, user_id: str, pool_id: int) -> dict:
        """
        首次访问指定卡池时自动创建 pull_count=0 的记录。
        返回 {"pull_count": int, "has_seen_5star_above": int}
        """
        # 确保用户记录存在（user_pool_first_pull 外键依赖 users）
        self.get_or_create_user(user_id)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT pull_count, has_seen_5star_above FROM user_pool_first_pull "
                "WHERE user_id = ? AND pool_id = ?",
                (user_id, pool_id),
            ).fetchone()
            if row is None:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO user_pool_first_pull (user_id, pool_id, pull_count, has_seen_5star_above, updated_at) "
                    "VALUES (?, ?, 0, 0, ?)",
                    (user_id, pool_id, now),
                )
                conn.commit()
                return {"pull_count": 0, "has_seen_5star_above": 0}
            return {"pull_count": row["pull_count"], "has_seen_5star_above": row["has_seen_5star_above"]}

    def get_first_ten_state(self, user_id: str, pool_id: int) -> Tuple[int, bool]:
        """
        获取指定卡池的首发保底状态，供十连抽卡传入引擎。
        返回 (pull_count, has_seen_5star_above)
        """
        rec = self._ensure_first_pull_record(user_id, pool_id)
        return rec["pull_count"], bool(rec["has_seen_5star_above"])

    def check_first_ten_trigger(self, user_id: str, pool_id: int, current_rarity: int) -> bool:
        """
        单抽后调用。判断是否应把本抽强制替换为 5★。
        触发条件: 本抽为累计第 10 抽 且 前 10 抽从未出过 ≥5★ 且 本抽结果 <5★。
        """
        rec = self._ensure_first_pull_record(user_id, pool_id)
        if rec["has_seen_5star_above"]:
            return False
        if rec["pull_count"] + 1 == 10 and current_rarity < 5:
            return True
        return False

    def increment_pull_count(self, user_id: str, pool_id: int, rarity: int):
        """
        每次抽卡后调用。pull_count+1；若 rarity>=5 则 has_seen_5star_above 置 1。
        """
        # 确保用户记录存在（user_pool_first_pull 外键依赖 users）
        self.get_or_create_user(user_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seen = 1 if rarity >= 5 else 0
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO user_pool_first_pull
                   (user_id, pool_id, pull_count, has_seen_5star_above, updated_at)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(user_id, pool_id) DO UPDATE SET
                       pull_count = pull_count + 1,
                       has_seen_5star_above = MAX(has_seen_5star_above, excluded.has_seen_5star_above),
                       updated_at = excluded.updated_at""",
                (user_id, pool_id, seen, now),
            )
            conn.commit()

    def get_pool_pull_count(self, user_id: str, pool_id: int) -> int:
        """
        获取指定用户在该卡池的累计抽数。
        记录不存在时自动创建并返回 0。
        """
        rec = self._ensure_first_pull_record(user_id, pool_id)
        return rec["pull_count"]
