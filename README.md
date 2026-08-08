# DM Workshop

> 新战役必须从 12 个一级核心职业预设中选择至少一名角色，并为每个角色命名；同一职业可重复选择。通过 MCP 的 `actors/list_actor_presets` 或 Web 的 `GET /api/actor-presets` 查询预设。`create_actor` 不再作为 MCP、Web 或前端功能公开。

DM Workshop 是一个面向 D&D 5e（2014 规则）的本地 DM 工具与状态服务。它通过 MCP 为 AI Agent 提供结构化的战役状态查询与操作能力，并提供 React Web 管理台用于查看、修正和撤销操作。

## 当前能力

- 多战役、多角色和稳定 UUID，允许同名角色及怪物
- 完整基础角色卡、HP/临时 HP、抗性、状态和明确的生死状态机
- 物品堆叠、装备、标准负重、共享仓库和中英文检索
- 商店库存、整数 GP 单币种、购买/出售和事务回滚
- 无地图先攻与回合、行动经济、武器攻击、死亡豁免和结构化施法
- SQLite 操作审计及冲突安全的补偿式撤销
- 八施法职业的 2014 多职业法术位、已知/准备规则和邪术师契约魔法
- 3 个标准 stdio MCP 路由工具（覆盖 42 个内部动作）和本机 React 管理台

内置目录是用于验证完整流程的 SRD 入门子集。项目根目录可选的 `spells.db`
作为用户提供的本地只读目录使用：程序会把 1071 个原始行清洗为 356 个唯一
法术，但不会提交、打包或声明该文件可再分发。

## 启动

```powershell
cd D:\Trial\DM_workshop
python -m pip install -e ".[dev]"
cd frontend
npm.cmd install
npm.cmd run build
cd ..
python -m dm_workshop web
```

浏览器访问 `http://127.0.0.1:8765`。数据库默认位于
`data/dm_workshop.db`，可通过 `DM_WORKSHOP_DB` 指定其他路径。

启动 MCP 服务：

```powershell
python -m dm_workshop mcp
```

## MCP 配置

Codex 配置示例：

```toml
[mcp_servers.dm_workshop]
command = "python"
args = ["-m", "dm_workshop", "mcp"]
cwd = "D:\\Trial\\DM_workshop"

[mcp_servers.dm_workshop.env]
DM_WORKSHOP_SPELLS_DB = "D:\\Trial\\DM_workshop\\spells.db"
```

Claude Desktop 配置示例：

```json
{
  "mcpServers": {
    "dm-workshop": {
      "command": "python",
      "args": ["-m", "dm_workshop", "mcp"],
      "cwd": "D:\\Trial\\DM_workshop",
      "env": {
        "DM_WORKSHOP_SPELLS_DB": "D:\\Trial\\DM_workshop\\spells.db"
      }
    }
  }
}
```

MCP 默认只公开 `list_capability_groups`、`list_group_actions` 和
`call_capability`。AI 应先读取大类，再读取相关动作清单，最后使用原动作名
通过 `call_capability` 调用；不要直接假设或猜测实体 ID。

## 验证

```powershell
python -m pytest -q
cd frontend
npm.cmd run build
```

SRD 归属与许可见 [NOTICE.md](NOTICE.md)。

## 环境与接口

建议使用 Python 3.12+ 和 Node.js 20+。Web 服务默认只监听本机，只有明确
需要局域网访问时才应修改 `--host`：

```powershell
python -m dm_workshop web --host 127.0.0.1 --port 8765
```

启动后可访问 `/docs` 查看 FastAPI 生成的交互式接口文档。主要接口如下：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 存活检查 |
| `GET/POST` | `/api/campaigns` | 查询或创建战役 |
| `GET` | `/api/campaigns/{id}` | 完整权威状态 |
| `GET` | `/api/campaigns/{id}/summary` | 紧凑摘要 |
| `POST` | `/api/campaigns/{id}/commands/{name}` | 执行业务命令 |
| `GET` | `/api/campaigns/{id}/operations` | 查询审计记录 |
| `POST` | `/api/campaigns/{id}/undo/{operation_id}` | 撤销最新写操作 |

业务错误返回 `422`，实体不存在返回 `404`，修订冲突或不可撤销返回 `409`。

## 推荐 MCP 工作流

1. 调用 `list_capability_groups` 查看 7 个功能大类。
2. 按当前任务调用 `list_group_actions(group)`，读取该大类的动作说明。
3. 使用 `call_capability(group, action, arguments)` 调用具体动作；动作名仍使用
   原有函数名，例如 `list_campaigns`、`get_campaign_summary` 或
   `search_spell_catalog`。
4. 用 `get_spell_details` 按需读取法术正文，不要把全部法术正文放入上下文。
5. 写操作仍先进入内存草稿；只有用户明确要求时，才通过
   `call_capability("campaign", "save_campaign", ...)` 保存。

角色、怪物和物品可以重名，因此不能根据名称猜测 UUID。共享仓库的固定
owner ID 为 `party`。

默认严格执行职业列表、可用环位、已知/准备上限和多职业属性前提。DM 确需
特批时应提供非空 `override_reason`；该原因会进入事务审计。自然语言效果仅在
高置信度时自动结算，返回 `manual_resolution_required` 时必须由 DM 阅读正文
裁定，不能让 AI 猜测效果。

## 数据安全

每次修改都会在同一个 SQLite 事务内完成规则校验、修订推进、快照保存和审计
写入。撤销不会删除历史，而是创建恢复操作前状态的新事务；目标操作之后若有
其他写入，系统会拒绝自动撤销，避免覆盖新数据。

可通过环境变量指定独立战役数据库和外部法术目录：

```powershell
$env:DM_WORKSHOP_DB = "D:\data\my-campaign.db"
$env:DM_WORKSHOP_SPELLS_DB = "D:\Trial\DM_workshop\spells.db"
python -m dm_workshop web
```

备份前应停止 Web 和 MCP 进程，再复制数据库。SQLite 使用 WAL 模式，运行中
只复制 `.db` 文件可能遗漏尚在 `.db-wal` 中的数据。

## 当前限制

- 外部 `spells.db` 的来源与再分发权未确认，只能作为本地用户数据使用。
- 战斗不处理地图、距离、范围、掩护、机会攻击和复杂反应时机。
- 专注、多目标、持续、召唤和 `utility` 法术通常只记录事件，由 DM 裁定。
- 法术当前按单一目标结算；范围法术需要对目标分别处理。
- 不包含领域、誓言、奥法骑士、诡术师等子职业额外法术表。
- Web 管理台覆盖常用流程，完整能力以 MCP 工具和服务层为准。
- 系统面向可信本机使用，没有账户、权限和远程访问认证。

## 项目结构与维护

```text
dm_workshop/          Python 领域服务、SQLite 存储、Web 与 MCP 适配层
spells.db             可选的本地外部法术库（不提交、不分发）
frontend/src/         React 管理台
tests/                规则、事务、Web 和 MCP 回归测试
data/                 默认本地数据库（不应提交）
docs/ARCHITECTURE.md  架构、状态和扩展约束
```

若从旧环境复制项目后遇到 `tsconfig.app.tsbuildinfo` 权限错误，可删除该生成
文件。当前构建脚本不依赖增量缓存，正常情况下不会重新生成它。

详细维护说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
