"""
从 PRTS Wiki 获取「卡池一览」页面的原始 wikitext
输出到 ../data/raw/gacha_wikitext.json
"""
import json
import os
from curl_cffi import requests

PRTS_API = "https://prts.wiki/api.php"
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "gacha_wikitext.json")


def fetch_current_gacha_raw():
    params = {
        "action": "parse",
        "page": "卡池一览",
        "prop": "wikitext",
        "format": "json",
    }
    print(">> 正在从 PRTS Wiki 获取卡池一览 wikitext...")
    response = requests.get(PRTS_API, params=params, impersonate="chrome110", timeout=30)
    if response.status_code == 200:
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with open(OUTPUT, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f">> 原始数据已保存: {OUTPUT}")
    else:
        print(f"!! 请求失败，状态码: {response.status_code}")


if __name__ == "__main__":
    fetch_current_gacha_raw()
