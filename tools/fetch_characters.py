"""
从 PRTS Wiki 获取干员完整信息（含 charId、中文名、稀有度、职业、获取方式等）
输出到 ../data/raw/characters_raw.json

【重要】MediaWiki 的 cargoquery 单次请求最多返回 500 条。若固定用 limit=500 拉取，
干员总数一旦超过 500，就会静默漏掉一部分干员（新上线干员首当其冲），
表现为"卡池里抽得到、但缺少职业图标/职业信息"。
因此这里改为【分页全量拉取】：循环带 offset 直到取完全部干员。
"""
import json
import os
import sys

from curl_cffi import requests

# 运行时数据目录统一由 composer_config 提供。
# 插件以子进程方式调用本脚本时会注入 ARKGACHA_DATA_DIR 环境变量，
# 确保写入位置与插件读取位置一致；手动运行时则回退到插件目录下的 data/。
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Script"))
import composer_config as cfg  # noqa: E402

PRTS_API = "https://prts.wiki/api.php"
OUTPUT = os.path.join(cfg.RAW_DIR, "characters_raw.json")
cfg.ensure_data_dirs()   # 确保输出目录存在（否则写入会因 [Errno 2] 失败）

# MediaWiki cargoquery 单次请求上限
PAGE_SIZE = 500
# 分页安全上限：防止接口异常（如 offset 不生效）时无限循环
MAX_PAGES = 40

FIELDS = (
    "chara.charId=charId, chara.cn=cn, chara.en=en, chara.rarity=rarity, "
    "chara.profession=profession, chara.subProfession=subProfession, "
    "chara.logo=logo, "
    "char_obtain.cnOnlineTime=cnOnlineTime, char_obtain.obtainMethod=obtainMethod"
)


def fetch_chara_page(limit=PAGE_SIZE, offset=0):
    """拉取一页干员数据（最多 limit 条）"""
    params = {
        "action": "cargoquery",
        "tables": "chara,char_obtain",
        "join_on": "chara._pageName=char_obtain._pageName",
        "fields": FIELDS,
        "order_by": "chara.charId ASC",
        "limit": str(limit),
        "offset": str(offset),
        "format": "json",
    }
    response = requests.get(PRTS_API, params=params, impersonate="chrome110", timeout=60)
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"PRTS cargoquery 返回错误: {payload['error']}")
    return payload.get("cargoquery", [])


def fetch_chara_all():
    """
    分页拉取全部干员，返回去重后的列表。

    去重键为 charId（char_obtain 可能存在多行，导致同一干员重复返回）。
    """
    all_rows = []
    seen = set()
    offset = 0

    for page in range(MAX_PAGES):
        batch = fetch_chara_page(PAGE_SIZE, offset)
        if not batch:
            break

        for row in batch:
            title = row.get("title", {})
            key = title.get("charId") or title.get("cn")
            if not key or key in seen:
                continue
            seen.add(key)
            all_rows.append(row)

        print(f"   第 {page + 1} 页: 本页 {len(batch)} 条, 累计去重 {len(all_rows)} 条")

        # 不足一整页说明已到末页
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_rows


# 兼容旧调用名
fetch_chara_combined = fetch_chara_all


if __name__ == "__main__":
    print(">> 正在从 PRTS 获取干员数据（全量分页）...")
    raw_data = fetch_chara_all()
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"cargoquery": raw_data}, f, ensure_ascii=False, indent=2)
    print(f">> 成功提取 {len(raw_data)} 条干员数据 -> {OUTPUT}")
