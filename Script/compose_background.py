# -*- coding: utf-8 -*-
"""
一次性脚本：把 gacha_beijing_2.png（远景：光晕+人物剪影）与
gacha_beijing_1.png（前景：灯柱+地面）预合成为一张永久背景图。

合成算法与 image_renderer 渲染时完全一致：
1. 最底层铺纯黑 (0,0,0,255) 实底
2. 先铺远景 beijing_2（resize 到画布尺寸，亮度 0.5）
3. 再叠前景 beijing_1（resize 到画布尺寸，亮度 0.5）
全程用 Image.alpha_composite 做像素级 RGBA 混合，最后转 RGB 丢弃 alpha。

用法：python compose_background.py
输出：gacha_primary_material/gacha_beijing_composed.png
"""
import os
import sys
from PIL import Image

# 画布尺寸与 image_renderer 保持一致（源素材裁剪后为 1024x576）
CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 576

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATERIAL_DIR = os.path.join(PLUGIN_DIR, "gacha_primary_material")

# POT 纹理裁剪常量：源素材 1024x1024，有效区域为中间 1024x576
SRC_POT_SIZE = 1024
SRC_EFFECTIVE_HEIGHT = 576


def load_safe(path):
    if os.path.isfile(path):
        return Image.open(path).convert("RGBA")
    return None


def _prepare_background(img: Image.Image):
    """
    智能处理背景素材，保证输出尺寸恒为 CANVAS_WIDTH x CANVAS_HEIGHT (1024x576)：
    1. POT 正方形纹理 (1024x1024)：裁剪中间 1024x576 有效区域，去掉上下黑边
    2. 非正方形素材：等比缩放到画布尺寸
    3. 已是 1024x576 的图：原样返回
    """
    iw, ih = img.size
    # 1. POT 正方形纹理：裁剪中间有效区域
    if iw == ih and iw >= SRC_POT_SIZE:
        crop_top = (iw - SRC_EFFECTIVE_HEIGHT) // 2
        img = img.crop((0, crop_top, iw, iw - crop_top))
    # 2. 统一缩放到画布尺寸
    if img.size != (CANVAS_WIDTH, CANVAS_HEIGHT):
        img = img.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.LANCZOS)
    return img


def main():
    far_path = os.path.join(MATERIAL_DIR, "gacha_beijing_2.png")
    near_path = os.path.join(MATERIAL_DIR, "gacha_beijing_1.png")

    far = load_safe(far_path)
    near = load_safe(near_path)
    if far is None or near is None:
        missing = [p for p, im in [(far_path, far), (near_path, near)] if im is None]
        print("缺失背景素材:", missing)
        return 1

    print(f"远景 beijing_2: {far.size} mode={far.mode}")
    print(f"前景 beijing_1: {near.size} mode={near.mode}")

    # 最底层纯黑不透明实底
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 255))

    # 先铺远景：裁剪 POT 填充的上下黑边 → 恢复 1024x576 正确比例（保持原图亮度）
    far = _prepare_background(far)
    canvas = Image.alpha_composite(canvas, far)

    # 再叠前景：同上裁剪（保持原图亮度）
    near = _prepare_background(near)
    canvas = Image.alpha_composite(canvas, near)

    out_path = os.path.join(MATERIAL_DIR, "gacha_beijing_composed.png")
    canvas.convert("RGB").save(out_path, "PNG")
    print("已生成永久合成背景:", out_path)
    print("尺寸:", canvas.size, "mode:", canvas.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
