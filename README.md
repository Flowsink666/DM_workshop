# DM Workshop

> 面向 D&D 5e（2014 规则）的本地战役状态引擎与 DM 辅助工作台。

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![MCP](https://img.shields.io/badge/MCP-2.0-8A2BE2.svg)](https://modelcontextprotocol.io/)

DM Workshop 是专为 **“AI 辅助跑团 / AI 担任地下城主（DM）”** 打造的本地规则裁判中枢。

在 AI 跑团时，大语言模型常常会出现“遗忘角色生命值、算错多职业法术位、凭空造出道具”等幻觉问题。DM Workshop 将**严谨的规则裁定与状态管理**从大模型中剥离出来——让底层程序担任“铁面无私的规则裁定者”，大模型只需专注剧情演绎与 NPC 扮演；同时为人类 DM 提供轻量直观的 Web 管理台，支持随时查看状态、人工微调与一键回滚。

---

## ✨ 核心特性

- **🛡️ 纯正的 D&D 5e 核心规则沉淀**
  - **角色卡与生命状态机**：完整记录 HP、临时 HP、护甲等级（AC）、豁免加值与 14 种标准异常状态；严谨维护清醒、倒地、昏迷、稳定与死亡状态机。
  - **12 大核心职业开箱即用**：内置 12 个一级核心职业预设（战士、法师、牧师、游荡者等），支持自由组合队伍与同职业多角色。
  - **多职业施法体系**：严格按照 2014 规则自动计算多职业复合施法位、已知/准备法术容量、法术书抄录；独立区分邪术师契约魔法（Pact Magic）与玄奥秘法（Mystic Arcanum），支持仪式施法（Ritual Casting）。
  - **背包、负重与经济**：支持物品堆叠、部位装备、标准负重上限校验（`力量 × 15 磅`）、小队共享仓库以及整数 GP 金币系统。
  - **轻量无网格战斗遭遇**：自动掷先攻、维护行动轮次与行动经济；支持武器攻击、伤害减免/抗性计算、战斗施法与死亡豁免判定。

- **💾 安全的“草稿 + 命名存档”机制**
  - **操作先入草稿**：无论是 AI 判定还是 Web 修改，均先写入内存工作区草稿，跑团偏离预期时随时可以“一键丢弃修改”。
  - **命名存档与随时回滚**：关键剧情节点可随时创建命名快照（如“深入地牢前”、“巨龙决战前”），支持跨存档加载与多进程并发安全校验（`BEGIN IMMEDIATE` 互斥保护）。

- **🤖 专为大模型设计的 MCP 适配层**
  - 采用 **3 个标准路由工具** 收敛 38 项内部功能，防止数十个工具淹没模型上下文。
  - 智能紧凑回执（Receipt）：写操作仅返回关键差异摘要，按需获取法术正文，极大节约 Token 消耗。

- **🖥️ 现代化的 Web 管理面板**
  - 预构建 React 19 单页应用，开箱即用，手机或电脑浏览器均可访问。
  - 包含总览仪表盘、角色详细属性卡、背包装备栏、战斗遭遇轮次表与存档管理器。

---

## 🚀 快速上手

### 1. 环境准备

- **Python** 3.12+
- **Node.js** 20+（仅在需要重新构建前端时需要；项目中已包含预构建好的静态页面）

### 2. 安装与运行

克隆本项目到本地后，在命令行中进入项目根目录：

```powershell
# 1. 安装 Python 核心及开发依赖
python -m pip install -e ".[dev]"

# 2. （可选）如果修改了前端源码，重新构建前端
cd frontend
npm install
npm run build
cd ..

# 3. 启动 Web 管理台
python -m dm_workshop web
```

启动后在浏览器打开 `http://127.0.0.1:8765` 即可使用。
默认数据库存放在 `data/dm_workshop.db`，如需自定义路径可设置环境变量 `DM_WORKSHOP_DB`。

> 💡 **小贴士**：如果你希望在**同一个进程**中同时运行 MCP 服务和 Web 面板，可直接执行：
> ```powershell
> python -m dm_workshop serve
> ```

---

## 🔌 接入 AI Agent（MCP 配置）

DM Workshop 实现了标准的 Model Context Protocol（stdio 模式），能够直接接入 Claude Desktop、Cursor、VS Code 或任意兼容 MCP 的 Agent 客户端。

单独启动 MCP 服务命令为：
```powershell
python -m dm_workshop mcp
```

### Claude Desktop 配置示例

在 Claude Desktop 的配置文件中（如 `%APPDATA%\Claude\claude_desktop_config.json`）添加：

```json
{
  "mcpServers": {
    "dm-workshop": {
      "command": "python",
      "args": ["-m", "dm_workshop", "mcp"],
      "cwd": "C:\\path\\to\\DM_workshop",
      "env": {
        "DM_WORKSHOP_SPELLS_DB": "C:\\path\\to\\DM_workshop\\spells.db"
      }
    }
  }
}
```

### 通用 / Codex 配置示例

```toml
[mcp_servers.dm_workshop]
command = "python"
args = ["-m", "dm_workshop", "mcp"]
cwd = "C:\\path\\to\\DM_workshop"

[mcp_servers.dm_workshop.env]
DM_WORKSHOP_SPELLS_DB = "C:\\path\\to\\DM_workshop\\spells.db"
```

> **AI 使用说明**：
> 接入后，MCP 会暴露 `list_capability_groups`、`list_group_actions` 和 `call_capability` 三个路由工具。Agent 会按需按功能大类读取动作并调用，避免一次性加载过多工具说明。

---

## 📖 Web 管理台界面速览

Web 界面包含 5 大核心功能模块：

| 模块 | 功能说明 |
| :--- | :--- |
| **总览 (Overview)** | 查看存活角色数量、物品总数、当前活动遭遇进度以及队伍血量 AC 概览卡片。 |
| **角色 (Actors)** | 查看完整角色卡，调整属性与速度；支持一键扣除伤害、治疗以及发起短休/长休。 |
| **背包 (Inventory)** | 管理个人背包与队伍共享小队仓库；装备/卸下武器防具，实时监控标准负重超载状态。 |
| **战斗 (Combat)** | 创建 PC 与敌方阵营遭遇，一键掷先攻并按轮次推进；提供攻击、施法、死亡豁免和回合结束按钮。 |
| **存档 (Saves)** | 浏览所有历史保存点；支持将当前草稿保存为新存档、覆盖当前存档或随时回滚到指定历史状态。 |

---

## 📜 REST API 概览

Web 界面与第三方客户端均可通过本地 REST API 进行交互。启动 Web 服务后访问 `http://127.0.0.1:8765/docs` 可查看完整的 Swagger 交互式文档：

| 请求方式 | 接口路径 | 作用说明 |
| :--- | :--- | :--- |
| `GET` | `/api/health` | 服务健康检查 |
| `GET` | `/api/actor-presets` | 获取 12 大核心职业初始化预设 |
| `GET / POST` | `/api/campaigns` | 查询现有战役列表 / 初始化新战役 |
| `GET` | `/api/campaigns/{id}` | 读取战役完整权威状态 |
| `GET` | `/api/campaigns/{id}/summary` | 读取角色与战斗紧凑摘要 |
| `POST` | `/api/campaigns/{id}/commands/{name}` | 执行业务命令（写入内存草稿） |
| `GET` | `/api/campaigns/{id}/saves` | 查询历史命名存档列表 |
| `POST` | `/api/campaigns/{id}/save` | 将当前草稿持久化为命名存档 |
| `POST` | `/api/campaigns/{id}/discard` | 放弃当前所有未保存修改 |
| `POST` | `/api/campaigns/{id}/saves/{save_id}/load` | 恢复并加载指定存档 |

---

## 🔮 外部法术扩展库（可选）

项目内置了满足流程测试的常用 SRD 法术子集。如果你手头拥有更完整的 5e 本地法术数据库（如私有整理的 `spells.db`）：
1. 将 `spells.db` 放置在项目根目录下（或配置环境变量 `DM_WORKSHOP_SPELLS_DB`）；
2. 引擎会自动读取、清洗与匹配（支持 300+ 完整中文法术及学派检索）；
3. 当角色学习某法术后，该法术会自动持久化到当前战役快照中，不再依赖外部数据库文件。

---

## 📐 设计边界与说明

- **战术地图**：本工具专注战役数值、状态与文字跑团推进，不提供战棋格子、视线遮蔽与距离网格渲染。
- **复杂法术效果裁定**：直接伤害、攻击检定、治疗类法术可自动结算；复杂的环境召唤、长效专注或剧情向法术，系统会标记为 `manual_resolution_required`，由 DM（或人类玩家）根据正文判定。
- **安全性与网络**：服务默认仅监听本机回环地址（`127.0.0.1`），设计为完全本地可信运行，不包含公网鉴权体系。

---

## 📄 许可与致谢

- 5e 规则内容与 SRD 声明详见 [NOTICE.md](NOTICE.md)。
- 详细架构分层与扩展约束请参阅 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
