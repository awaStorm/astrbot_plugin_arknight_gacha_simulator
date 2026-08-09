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

---

## 项目结构

```
astrbot_plugin_arknight_gacha_simulator/
├── main.py                       # 插件主入口：命令注册、生命周期、数据加载
├── metadata.yaml                 # 插件元数据（AstrBot 识别用）
├── _conf_schema.json             # 配置项 schema
├── requirements.txt              # Python 依赖
├── push.bat                      # 一键提交并推送 GitHub 脚本
├── data/
│   ├── gacha_table.json          # 官方卡池表（随版本更新）
│   └── processed/                # 处理后的卡池/规则数据（运行时生成，已 gitignore）
├── Script/                       # 核心逻辑模块
│   ├── gacha_engine.py           # 抽卡概率引擎（软保底 / UP / 各池型规则）
│   ├── image_composer.py         # 图片合成器（构图、光效、星点着色）
│   ├── composer_config.py        # 合成参数配置
│   ├── image_renderer.py         # 渲染器对外接口 + 头像/职业图标缓存
│   ├── compose_background.py     # 背景合成
│   ├── pool_generator.py         # 由清洗数据生成 active_pools / pool_rules
│   ├── auto_updater.py           # 自动数据更新调度
│   └── database.py               # SQLite 数据持久化
├── tools/                        # 离线数据处理工具
│   ├── fetch_gacha_wikitext.py   # 抓取 PRTS 卡池一览 wikitext
│   ├── clean_gacha_pools.py      # 解析并分类卡池（含池型识别）
│   ├── post_process_pools.py     # 后处理：UP 干员标注、时间校验
│   ├── update_all.py             # 一键跑全量数据流水线
│   └── ...
└── gacha_primary_material/       # 本地素材（卡池封面、光效贴图等）
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

## 许可

本项目使用 [MIT License](LICENSE)。

所有干员立绘、卡池封面、音效等素材版权归 **© HYPERGRYPH（鹰角网络）** 及 **PRTS Wiki** 所有，仅供个人娱乐与学习使用，请勿用于商业用途。
