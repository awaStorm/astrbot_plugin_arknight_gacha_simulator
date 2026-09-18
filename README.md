# astrbot_plugin_arknight_gacha_simulator

一个运行于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 平台的**明日方舟抽卡模拟器插件**。

该插件忠实还原明日方舟的抽卡机制与概率规则，支持**多卡池并行**、**签到领抽**、**单抽 / 十连**、**潜能仓库**与**结果图片渲染**。卡池数据自动同步自 PRTS Wiki 与官方 `gacha_table.json`，覆盖标准寻访、限定寻访、中坚寻访、联动寻访、定向甄选等全部卡池类型。

---

## 功能特性

- 🎴 **多卡池并行**：同时展示当前进行中的全部卡池，覆盖标准 / 限定 / 中坚 / 联动 / 定向 / 新人 / 跨年欢庆等池型。
- 📊 **忠实概率机制**：完整还原 6★ 基础出率与递增软保底、10 连保底 5★、UP 干员比例、限定池 70% UP 及保底计数不跨期继承等规则。
- 📅 **每日签到**：每日可领取 10 次抽卡机会。
- 🎯 **单抽 / 十连**：支持在指定卡池中进行单抽或十连，输出文字结果与合成图片。
- ⭐ **潜能仓库**：记录已获取干员及潜能数，支持按星级分页查看。
- 🖼️ **图片渲染**：通过解包获得的相关原始素材，生成带光效、光晕、星点着色的高还原度抽卡结果图。
- 🔄 **自动数据更新**：启动时自动对比官方数据并同步卡池，无需手动维护。
- 🔒 **数据隔离**：抽卡次数、签到记录、潜能仓库数据均存储于独立 SQLite 数据库。
- ✴️ **潜能兑换抽数**： 支持将潜能兑换为抽卡次数，并自动更新抽卡次数（即将推出）

---

## 安装

### 方法一：AstrBot 插件市场

在 AstrBot WebUI 的 **插件管理** → **插件市场** 中搜索 `arknight_gacha_simulator` 并安装。

### 方法二：本地安装

将本仓库克隆或下载到 AstrBot 的插件目录：

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/awaStorm/astrbot_plugin_arknight_gacha_simulator.git
```

然后在 AstrBot 插件管理界面**启用**该插件即可。插件首次启动会自动完成数据初始化与资源准备。

### 依赖

插件会自动安装以下依赖（`requirements.txt`）：

| 依赖 | 用途 |
|------|------|
| `aiohttp>=3.9.0` | 网络请求（卡池封面、头像下载） |
| `curl_cffi>=0.7.0` | PRTS Wiki / Cargo API 数据抓取 |
| `Pillow>=10.0.0` | 抽卡结果图片合成 |

---

## 使用说明

### 命令列表

| 命令 | 说明 |
|------|------|
| `/抽卡帮助` | 显示所有抽卡命令及说明 |
| `/抽卡签到` | 每日签到，领取 10 次抽卡机会 |
| `/单抽 <池编号>` | 在指定卡池进行 1 次单抽 |
| `/十连 <池编号>` | 在指定卡池进行 10 连抽 |
| `/卡池查询` | 查看当前进行中的卡池（含 PRTS 卡池封面） |
| `/潜能仓库` | 查看已获得干员及潜能数 |
| `/潜能仓库 <星级>` | 查看指定星级干员（分页显示） |
| `/潜能仓库 <星级> <页码>` | 翻页查看潜能仓库 |

> 池编号可通过 `/卡池查询` 查看当前活动卡池对应的编号。

### 卡池类型

| 池类型 | 说明 |
|--------|------|
| `NORM` | 标准寻访 |
| `CLASSIC` | 中坚寻访 |
| `SINGLE` | 限时单 UP |
| `DOUBLE` | 限时双 UP / 联合行动 |
| `LIMITED` | 限定寻访（含限定干员 + 陪跑，6★ UP 70%） |
| `LINKAGE` | 联动寻访 |
| `SPECIAL` | 定向甄选 |
| `BOOT` | 新人特惠 |
| `ATTAIN` | 跨年欢庆 |
| `CLASSIC_ATTAIN` | 跨年欢庆·中坚 |

### 概率机制

- **6★ 基础出率**：2%，抽数越多软保底逐步提升，到达保底次数必定出 6★。
- **10 连保底**：首次 10 连内必定至少一个 5★。
- **UP 干员**：命中 6★ / 5★ 时，有一定概率抽中当前卡池的 UP 干员；限定池 6★ UP 总概率为 70%（限定干员与陪跑等权重各 35%）。
- **保底计数**：标准 / 中坚寻访的保底计数跨卡池期继承；限定池（`LIMITED`）保底计数**不**跨期继承。

---

## 配置项

插件支持在 AstrBot 的插件配置界面中调整以下参数：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `data_path` | string | `""` | `cleaned_pools_final.json` 的自定义路径。留空则使用插件自动生成的 `data/processed/` 目录 |
| `auto_update` | bool | `true` | 启动时是否自动从 GitHub / PRTS 更新卡池数据。**默认开启**：首次运行会拉取数据初始化 |
| `sign_in_amount` | int | `10` | 每日签到赠送的抽卡次数 |
| `portrait_cache_quality` | string | `original` | 单抽立绘**缓存画质**：`original` 原画质（不压缩，最清晰，占空间最大）/ `high` 1080px / `medium` 810px / `low` 640px。各档位独立缓存于 `data/cache/elite1_art/<档位>/`，切换后会重新下载立绘；不再使用的旧档位目录可手动删除 |

---

## 项目结构

```
astrbot_plugin_arknight_gacha_simulator/
├── main.py                       # 插件主入口：命令注册、生命周期、数据加载
├── metadata.yaml                 # 插件元数据（AstrBot 识别用）
├── _conf_schema.json             # 配置项 schema
├── requirements.txt              # Python 依赖
├── push.bat                      # 一键提交并推送 GitHub 脚本
├── data/                         # 运行时数据（本地调试时的默认位置，已 gitignore）
│   ├── gacha_table.json          # 官方卡池表（随版本更新）
│   └── processed/                # 处理后的卡池/规则数据（运行时生成）
├── Script/                       # 核心逻辑模块
│   ├── gacha_engine.py           # 抽卡概率引擎（软保底 / UP / 各池型规则）
│   ├── image_composer.py         # 图片合成器（构图、光效、星点着色）
│   ├── composer_config.py        # 合成参数配置（单抽构图参数集中在此调整）
│   ├── text_render.py            # 双语文字渲染（描边 + 填充，中英字体自动分工）
│   ├── camp_logo_map.py          # 干员阵营 → 阵营 Logo 映射表（未命中降级为罗德岛）
│   ├── font_manager.py           # 字体资源管理（首次运行时下载 + SHA-256 校验 + 缓存）
│   ├── image_renderer.py         # 渲染器对外接口 + 头像/职业图标缓存
│   ├── compose_background.py     # 背景合成
│   ├── pool_generator.py         # 由清洗数据生成 active_pools / pool_rules
│   ├── auto_updater.py           # 自动数据更新调度
│   └── database.py               # SQLite 数据持久化
├── tools/                        # 离线数据处理 / 本地调试工具
│   ├── fetch_characters.py       # 抓取 PRTS 干员数据（含英文名与阵营字段）
│   ├── fetch_gacha_wikitext.py   # 抓取 PRTS 卡池一览 wikitext
│   ├── clean_gacha_pools.py      # 解析并分类卡池（含池型识别）
│   ├── post_process_pools.py     # 后处理：UP 干员标注、时间校验
│   ├── update_all.py             # 一键跑全量数据流水线
│   ├── test_single_pull.py       # 单抽结果图本地预览（免启动 AstrBot 调参）
│   └── ...
├── assets/
│   └── fonts/                    # 字体授权协议原文；字体本身不随包分发，运行时自动下载
└── gacha_primary_material/       # 本地素材（背景、装饰星、光柱、职业图标、阵营 Logo 等）
```

---

## 数据更新机制

插件**不内置任何卡池数据**（`data/` 目录全部由脚本在运行时生成）。启用 `auto_update`（默认开启）时，启动将自动执行数据拉取与更新流程：

1. **GitHub 对比**：通过 SHA256 对比官方 `gacha_table.json` 是否更新。
2. **PRTS 降级对比**：抓取 PRTS 卡池一览 wikitext，与本地数据对比池名与时间区间。
3. **全量流水线**：数据有变化时自动执行 `fetch → clean → post_process → pool_generator` 全流程并重载。

也可在项目根目录运行 `tools/update_all.py` 手动触发完整数据更新。

---

## 开发者说明

### 数据流水线

```
gacha_wikitext.json (PRTS)        gacha_table.json (官方)
        │                                 │
        ▼                                 ▼
tools/clean_gacha_pools.py ───► cleaned_pools.json
        │
        ▼
tools/post_process_pools.py ──► cleaned_pools_final.json
        │
        ▼
Script/pool_generator.py ──────► active_pools.json + pool_rules.json
        │
        ▼
main.py（运行时加载 + 引擎解析）
```

### 图片合成

`Script/image_composer.py` 的构图参数、光效布局、程序生成光晕/小亮条/星点着色等逻辑已 100% 复刻自 `Generator_test/image_composer.py` + `config.py`，确保渲染效果与测试版一致。

### 环境要求

- Python 3.10+
- AstrBot 4.x
- 需联网（数据更新、卡池封面 / 干员头像下载）

---

## 更新日志

### v0.4.3

**修复：从插件市场安装 / 更新后插件无法加载**

- 修复加载时报 `module 'composer_config' has no attribute 'set_data_dir'` 的问题。
  - **原因**：AstrBot 在同一进程内加载或热重载插件时，`sys.modules` 中可能残留**旧版本**或**其它插件**的同名模块。此时 `import composer_config` 会直接命中缓存，拿到的并非本插件的实现，从而缺少新增接口并导致加载中断。
  - **修复**：插件入口在首次导入前，先清理本插件所使用的同名模块缓存，并把本插件目录强制置于 `sys.path` 最前，确保后续导入一定解析到本插件 `Script/` 下的实现。

### v0.4.2

**框架合规化调整**

- **日志**：移除全部内置 `logging` 用法，统一改为从 `astrbot.api` 导入 `logger`（`Script/image_renderer.py`、`Script/font_manager.py`）。
- **数据持久化**：运行时数据（下载缓存、抓取数据、字体、SQLite 数据库）不再写入 AstrBot 的 `data/` 根目录，也不再写入插件安装目录，统一改由框架公开 API `StarTools.get_data_dir()` 分配插件专属目录 `data/plugin_data/<插件名>/`。
  - 插件入口 `main.py` 取得目录后注入 `composer_config.set_data_dir()`，各模块统一从 `composer_config` 取路径。
  - 插件以子进程方式调用 `tools/` 下的数据脚本时，通过 `ARKGACHA_DATA_DIR` 环境变量把该目录透传下去，保证子脚本写入位置与插件读取位置一致。
  - 脱离 AstrBot 手动运行 `tools/` 脚本（本地开发）时退回插件目录下的 `data/`。
  - **旧数据自动迁移**：检测到历史遗留数据时会自动迁移到新的专属目录，老用户升级后不会丢失抽卡次数、签到记录与潜能仓库。迁移分两处进行，且仅在「新位置尚不存在数据」时执行，绝不覆盖既有数据；失败也只告警，不影响插件启动：
    1. 插件安装目录 `data/` 下的缓存 / 抓取数据 / 字体 → 插件专属目录；
    2. AstrBot 数据根目录下的旧版 `user.db`（含 SQLite 的 `-wal` / `-shm` 伴生文件）→ 插件专属目录。第 2 项为**受限迁移**：只针对 `user.db` 这几个确定文件，不遍历、不读写该目录下的其它内容。

### v0.4.1

**轻量化包体**

- 字体文件不再随插件包分发，改为首次运行时从 **OpenHarmony 官方仓库**下载，并做 SHA-256 完整性校验后缓存到本地（详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)）。
- 插件包体积由约 21 MB 降至约 5 MB。

### v0.4.0

**单抽结果图全面重制**

- 新增**单抽结果图 v3 生成器**（元素表驱动），取代旧版"背景 + 立绘"的简易构图：背景 / 干员立绘 / 阵营 Logo / 带文字职业图标 / 星级五角星 / 中英文姓名 / 装饰星与光柱 / 暗角打光 / 底部渐变，全部元素的位置、大小、透明度、混合模式与层级统一集中在 `Script/composer_config.py` 中可视化调整。
- 新增**双语文字渲染**（`Script/text_render.py`）：中文与英文由同一字体的 CJK / 拉丁字形自动分工，支持描边 + 填充、字距、可变字重。
- 新增**阵营 Logo 映射**（`Script/camp_logo_map.py`）：覆盖 46 个阵营；阵营为空、映射未命中或图片缺失时统一降级为罗德岛。
- 新增**装饰星随机化**：每个副本独立随机尺寸（默认 60%~80%）与位置，并按概率 180° 翻转；翻转后的装饰星可单独设置色调（暖橙）与高度偏移，其附属光柱自动跟随同色。
- 新增**程序化柔光柱**：支持平顶比例、横纵向衰减、透明度与滤色混合，尺寸随装饰星等比缩放。
- 光柱层级改用**小数偏移**（默认 `+0.5`），使其稳定位于所属装饰星之下，且不会与相邻元素的整数层级发生冲突。

**资源与数据**

- 新增**带文字职业图标**预拉取：启动时并发拉取八大职业图标并永久缓存于 `data/cache/professions_labeled/`，原有不带文字的图标及其使用逻辑完全不受影响。
- 卡池封面改为**本地化缓存**：首次探测成功后下载至 `data/cache/pool_covers/` 并保留 30 天，之后直接发送本地文件，不再将 URL 交给下游加载；下载失败时自动回退原有行为。
- 干员数据抓取扩展 `en`（英文名）与 `logo`（阵营）字段。

---

## 许可

本项目使用 [MIT License](LICENSE)。

### 第三方字体

**本插件使用了 HarmonyOS Sans 字体。**

| 字体 | 版权 | 授权协议 | 获取方式 |
|------|------|----------|----------|
| **HarmonyOS Sans SC Bold** | © 2021 Huawei Device Co., Ltd. | HarmonyOS Sans Fonts License Agreement | 首次运行时从 [OpenHarmony 官方仓库](https://github.com/openharmony/utils_system_resources) 下载，SHA-256 校验后缓存于 `data/fonts/` |
| **Source Han Sans CN Heavy**（思源黑体，可选兜底） | © Adobe | SIL Open Font License 1.1 | 不自动下载，需自行放入 `assets/fonts/` |

**字体不随插件包分发**（以控制插件包体积），而是首次运行时从官方来源获取。
下载后先做 SHA-256 完整性校验再落盘，字体文件始终是**未经任何修改**的原样副本
（不做子集化、不改字形与元数据），协议文本会随字体一并保留在缓存目录中。

完整的第三方资源说明与许可合规要点见 **[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)**。

### 游戏素材

所有干员立绘、卡池封面、音效等素材版权归 **© HYPERGRYPH（鹰角网络）** 及 **PRTS Wiki** 所有，仅供个人娱乐与学习使用，请勿用于商业用途。
