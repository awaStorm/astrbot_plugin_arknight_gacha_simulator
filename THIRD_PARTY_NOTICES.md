# 第三方资源声明 / Third-Party Notices

本插件在运行过程中会使用下列第三方资源。为控制插件包体积，这些资源
**不包含在插件包内**，而是在首次需要时从各自的官方来源获取到本地使用。

---

## 1. HarmonyOS Sans Fonts

> **本插件使用了 HarmonyOS Sans 字体。**
> **This plugin uses HarmonyOS Sans Fonts.**

| 项目 | 内容 |
|------|------|
| 具体字体 | `HarmonyOS Sans SC Bold` |
| 版权所有者 | Copyright © 2021 Huawei Device Co., Ltd. |
| 授权协议 | HarmonyOS Sans Fonts License Agreement |
| 协议原文 | [`assets/fonts/LICENSE_HarmonyOS_Sans.txt`](assets/fonts/LICENSE_HarmonyOS_Sans.txt) |

### 获取方式

字体**不随本插件包分发**。插件首次运行时会从 **OpenHarmony 官方仓库**下载并缓存：

```
来源仓库：https://github.com/openharmony/utils_system_resources
文件路径：fonts/HarmonyOS_Sans_SC_Bold.ttf
固定提交：15ada4f9385a68ec18e2357c43dae158da723f39
SHA-256 ：705136d8e45591b6451da444f1c926b12b77536158f0bff744529b87010df3ee
```

下载完成后会进行 **SHA-256 完整性校验**，校验通过才会写入本地缓存
（`data/fonts/`）；校验不通过的文件会被直接丢弃，不会投入使用。

下载地址被固定到具体 commit，以保证内容长期稳定；如将来需要升级字体，
会同步更新提交号与哈希值。

### 协议要点

依据 HarmonyOS Sans Fonts License Agreement 第 2 条（GRANT OF LICENSE）：

- 允许将**未经修改的字体副本**用于 `use, copy, merge, embed, bundle, redistribute and/or sell`，条件是随附的软件**不是字体软件** —— 本插件为应用软件，符合该条件；
- **必须显著声明**使用了 HarmonyOS Sans 字体（即本文件及 `README.md` 中的声明）；
- **不得对字体做任何修改**（不改字形、不改元数据、不做子集化）—— 因此本项目**未**对字体做任何形式的压缩或裁剪，下载后原样缓存；
- **不得以独立形式**再分发或销售字体本身 —— 本项目不提供任何字体下载站，字体仅由使用者从官方仓库直接获取；
- 任何字体副本中**必须保留版权声明与本协议** —— 因此协议文本会随字体一并复制到 `data/fonts/` 目录。

完整条款请见 [`assets/fonts/LICENSE_HarmonyOS_Sans.txt`](assets/fonts/LICENSE_HarmonyOS_Sans.txt)，
或官方仓库的 [`LICENSE_Fonts`](https://github.com/openharmony/utils_system_resources/blob/master/LICENSE_Fonts)。

---

## 2. Source Han Sans（可选兜底字体）

| 项目 | 内容 |
|------|------|
| 具体字体 | `Source Han Sans CN Heavy`（思源黑体） |
| 版权所有者 | Copyright 2014-2025 Adobe (http://www.adobe.com/)，Reserved Font Name 'Source' |
| 授权协议 | SIL Open Font License 1.1 |
| 协议原文 | [`assets/fonts/LICENSE_SourceHanSans.txt`](assets/fonts/LICENSE_SourceHanSans.txt) |

该字体仅作为**兜底**：当 HarmonyOS Sans 不可用时，插件会尝试使用它。
本项目**不会自动下载**该字体，需要使用者自行将其放入 `assets/fonts/` 或 `data/fonts/`。

---

## 3. 游戏素材

所有干员立绘、卡池封面、职业图标、阵营 Logo、界面素材等版权归
**© HYPERGRYPH（鹰角网络）** 及 **PRTS Wiki** 所有，
仅供个人娱乐与学习使用，请勿用于商业用途。
