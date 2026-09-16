# -*- coding: utf-8 -*-
"""
test_single_pull.py - 单抽图片本地快速测试脚本（无需启动 AstrBot 插件）

作用:
    直接复用插件现有的图片渲染模块生成单抽结果图，用于在不启动插件的
    情况下快速预览 / 调整构图参数（参数文件: Script/composer_config.py）。

用法:
    python tools/test_single_pull.py                  # 默认生成「苏苏洛」4★
    python tools/test_single_pull.py 能天使            # 指定干员（星级默认 4）
    python tools/test_single_pull.py 能天使 6          # 指定干员 + 星级
    python tools/test_single_pull.py 苏苏洛 4 -o out   # 指定输出目录

说明:
    - 构图参数全部来自 Script/composer_config.py，脚本会打印当前关键参数。
    - 立绘下载 / 缓存逻辑复用 Script/image_renderer.ImageRenderer，
      与线上单抽完全一致（统一使用精英1立绘，缺失时兜底精英2立绘）。
    - 不依赖 AstrBot 运行时，不读写数据库。
"""
import argparse
import asyncio
import os
import sys

# ── 路径引导：使脚本从任意工作目录执行都能导入插件的 Script 模块 ──
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 插件根目录
SCRIPT_DIR = os.path.join(ROOT, "Script")
for _p in (ROOT, SCRIPT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import composer_config as cfg            # noqa: E402  读取构图参数
from image_renderer import ImageRenderer  # noqa: E402

# ── 默认值 ──
DEFAULT_NAME = "苏苏洛"
DEFAULT_RARITY = 4
DEFAULT_OUT = os.path.join(ROOT, "_tmp_out", "单抽测试")


def _print_cfg_summary():
    """打印当前生效的单抽构图参数，方便调参时对照"""
    print("── Script/composer_config.py 当前单抽参数 ──")
    print(f"  画布尺寸        : {cfg.SP3_CANVAS[0]}x{cfg.SP3_CANVAS[1]}")
    print(f"  背景亮度        : {cfg.BG_BRIGHTNESS}")
    print(f"  元素数量        : {len(cfg.SP3_ELEMENTS)}")
    enabled = [k for k, v in cfg.SP3_ELEMENTS.items() if v.get("enabled")]
    print(f"  启用元素        : {', '.join(enabled)}")
    print(f"  打光(暗角)      : {cfg.SP3_VIGNETTE.get('enabled')}")
    print(f"  立绘缓存目录    : {cfg.ELITE1_ART_DIR}")
    print("────────────────────────────────────────────")


async def _run(name: str, rarity: int, out_dir: str, is_new: bool = False) -> int:
    os.makedirs(out_dir, exist_ok=True)
    renderer = ImageRenderer(ROOT)
    await renderer.initialize()

    path = await renderer.render_single_pull(
        {"name": name, "rarity": rarity, "is_up": False},
        pool_name="本地测试", is_new=is_new,
    )
    if not path or not os.path.isfile(path):
        print(f"[FAIL] 未能生成图片: {name}（立绘不可用或渲染失败）")
        return 1

    # 从渲染器默认输出目录移动到测试输出目录，文件名带星级便于区分
    dst = os.path.join(out_dir, f"{rarity}星_{name}.png")
    os.replace(path, dst)
    print(f"[OK] 已生成: {dst}")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台中文输出
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="单抽图片本地快速测试（不启动插件）")
    ap.add_argument("name", nargs="?", default=DEFAULT_NAME,
                    help=f"干员名（默认 {DEFAULT_NAME}）")
    ap.add_argument("rarity", nargs="?", type=int, default=DEFAULT_RARITY,
                    help=f"星级（默认 {DEFAULT_RARITY}）")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT,
                    help="输出目录（默认 _tmp_out/单抽测试）")
    ap.add_argument("--new", action="store_true",
                    help="模拟首次获得（绘制 NEW 标记）")
    args = ap.parse_args()

    _print_cfg_summary()
    print(f"开始生成单抽图: {args.name} ({args.rarity}★){' [NEW]' if args.new else ''}")
    return asyncio.run(_run(args.name, args.rarity,
                            os.path.abspath(args.out), args.new))


if __name__ == "__main__":
    sys.exit(main())
