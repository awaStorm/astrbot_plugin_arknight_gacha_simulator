"""
从 PRTS Wiki 获取干员完整信息（含 charId、中文名、稀有度、职业、获取方式等）
输出到 ../data/raw/characters_raw.json
"""
import json
import os
from curl_cffi import requests

PRTS_API = "https://prts.wiki/api.php"
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "characters_raw.json")


def fetch_chara_combined(limit=500):
    params = {
        "action": "cargoquery",
        "tables": "chara,char_obtain",
        "join_on": "chara._pageName=char_obtain._pageName",
        "fields": "chara.charId=charId, chara.cn=cn, chara.rarity=rarity, "
                  "chara.profession=profession, chara.subProfession=subProfession, "
                  "char_obtain.cnOnlineTime=cnOnlineTime, char_obtain.obtainMethod=obtainMethod",
        "order_by": "chara.charId ASC",
        "limit": str(limit),
        "format": "json"
    }
    response = requests.get(PRTS_API, params=params, impersonate="chrome110", timeout=60)
    return response.json().get("cargoquery", [])


if __name__ == "__main__":
    print(">> 正在从 PRTS 获取干员数据...")
    raw_data = fetch_chara_combined()
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"cargoquery": raw_data}, f, ensure_ascii=False, indent=2)
    print(f">> 成功提取 {len(raw_data)} 条干员数据 -> {OUTPUT}")
