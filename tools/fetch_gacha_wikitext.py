"""
从 PRTS Wiki 获取「卡池一览」页面的原始 wikitext
输出到 ../data/raw/gacha_wikitext.json
"""
import json
import os
from curl_cffi import requests

import sys

# 运行时数据目录统一由 composer_config 提供（支持 ARKGACHA_DATA_DIR 环境变量）
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Script"))
import composer_config as cfg  # noqa: E402

PRTS_API = "https://prts.wiki/api.php"
OUTPUT = os.path.join(cfg.RAW_DIR, "gacha_wikitext.json")
cfg.ensure_data_dirs()   # 确保输出目录存在（否则写入会因 [Errno 2] 失败）


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
