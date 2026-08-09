"""
update_all.py - 全数据流水线一键更新
从 PRTS Wiki 获取最新数据 → 清洗 → 后处理
"""
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)


def run_step(label, script_name, *args):
    print(f"\n{'=' * 60}")
    print(f"  [{label}] 正在执行...")
    print(f"{'=' * 60}")
    script_path = os.path.join(SCRIPT_DIR, script_name)
    cmd = [sys.executable, script_path] + list(args)
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(f"!! [{label}] 失败，退出码 {result.returncode}")
        sys.exit(result.returncode)
    print(f">> [{label}] 完成")
    return result


def main():
    print("\n")
    print("=" * 60)
    print("  明日方舟卡池数据更新工具")
    print("  数据源: PRTS Wiki")
    print("=" * 60)

    # Step 1: 获取卡池 wikitext
    run_step("1/4", "fetch_gacha_wikitext.py")

    # Step 2: 获取干员稀有度信息
    run_step("2/4", "fetch_characters.py")

    # Step 3: 清洗卡池数据
    run_step("3/4", "clean_gacha_pools.py")

    # Step 4: 后处理（6星/5星分离等）
    run_step("4/4", "post_process_pools.py")

    print(f"\n{'=' * 60}")
    print("  全流程更新完成！")
    print(f"  最终数据: {os.path.join(SCRIPT_DIR, '..', 'data', 'processed', 'cleaned_pools_final.json')}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
