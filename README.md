# SQ-BI · 智慧问数

[![CI](https://github.com/renyumm/sq-bi/actions/workflows/ci.yml/badge.svg)](https://github.com/renyumm/sq-bi/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/renyumm/sq-bi?style=flat)](https://github.com/renyumm/sq-bi/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/renyumm/sq-bi)](https://github.com/renyumm/sq-bi/issues)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

面向制造、物流与企业运营的可治理 AI-Native BI。SQ-BI 让大模型负责理解问题、规划步骤和组织回答，让版本化指标、技能和报表负责确定性计算；每次回答保留资产、字段、数据源和血缘证据。

> 当前阶段：Community Preview。适合本地验证、产品共创和二次开发；面向公网或生产数据部署前，请完成密钥轮换、外部身份接入、持久化导出存储和安全评审。

## 它解决什么问题

SQ-BI 的直接用户是工厂/物流企业的经营人员、业务分析师，以及负责数据治理和交付的 IT/数据团队。

- 业务用户不必先学 SQL，能连续追问指标、下钻维度并获得合适的表格或趋势图。
- 分析师把口径、依赖和分析流程沉淀为指标、Skill 和报表，避免同一问题反复手工取数。
- 数据团队通过领域包把标准字段和资产挂载到不同语义空间，而不是把数据库结构写死在提示词里。
- 管理者能追溯回答使用了哪个版本的资产、哪些字段与数据源，而不是只能相信一段不可解释的生成 SQL。

## 核心洞察

企业问数的关键不是“让模型写出更多 SQL”，而是让模型在受控边界内调度可信资产：

```text
自然语言与上下文
      ↓
LLM 识别目标、参数、维度与展示意图
      ↓
正式指标/Skill/报表 → 语义空间探索 → 数据库 Catalog 探索
      ↓
受控工具、SQL 防护、预算和超时边界
      ↓
拟人化回答 + 自适应可视化 + 资产/字段/血缘证据
```

这带来四个差异点：领域包可移植且可扩建；正式资产优先但允许受控探索；多轮追问优先沿用原资产做维度下钻；AI 规划与确定性执行分离。

## 产品能力

- Oracle、PostgreSQL、MySQL、ClickHouse 数据源及独立连接生命周期。
- 官方/企业领域包、扩展层、字段映射、冒烟测试与激活状态机。
- `@` 指标、`/` Skill、`#` 报表的持续对话问数。
- 跨数据源受控规划、指标复用、维度下钻、趋势/对比展示。
- 个人资产的 AI 对话创建、受控测试、同步确认和版本引用。
- HTML 报告、导出、分享与订阅服务。
- SQL AST 防护、权限隔离、执行预算、审计与字段级血缘。

## 竞品如何解决

| 路线 | 典型产品 | 常见做法 | SQ-BI 的侧重点 |
|---|---|---|---|
| 传统 BI + Copilot | [Power BI Copilot](https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-introduction)、Tableau | 围绕语义模型、报表和可视化提供问答或辅助创作 | 领域包挂载、版本化执行资产和完整运行证据 |
| 搜索/对话分析 | ThoughtSpot 等 | 自然语言搜索、即时洞察与可视化 | 正式资产优先、失败不静默换口径、连续维度下钻 |
| 指标/语义层 | [dbt Semantic Layer](https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl)、[Cube](https://cube.dev/docs/product/semantic-layer/overview) | 集中定义指标并向多个消费工具提供一致语义 | 将指标继续组合为可调用 Skill、报告和 AI 工具链 |
| Text-to-SQL 框架 | Vanna、DB-GPT 等 | 用模型和 Schema/示例生成或检索 SQL | 默认不让模型直接生成任意 SQL，执行受资产和工具契约约束 |

SQ-BI 不试图替代所有可视化或数据建模工具；它更适合作为“可治理的对话分析与领域资产运行层”。

## 一键部署

要求：Podman Compose、`podman-compose` 或 Docker Compose 三者之一。

```bash
cp .env.example .env
# 编辑 .env，填写模型端点、模型名、API Key，并替换安全密钥
./scripts/deploy.sh up
```

浏览器访问 `http://localhost:8080`。脚本会自动识别容器运行时；常用操作：

```bash
./scripts/deploy.sh status
./scripts/deploy.sh logs
./scripts/deploy.sh restart
./scripts/deploy.sh down
```

默认账号仅用于本地首次登录：`admin / admin123`。登录后应立即在系统管理中修改密码。运行时状态保存在命名卷 `sqbi-data`；删除容器不会删除该卷。

## 本地开发

```bash
uv sync --all-packages --extra dev

# 后端（默认 http://127.0.0.1:8000）
cd services/runtime
uv run uvicorn sq_bi_runtime.api:app --reload

# 前端（默认 http://127.0.0.1:5173）
cd apps/web
npm ci
npm run dev
```

Export 服务可独立运行在 8001 端口；生产容器内由 Nginx 将导出/分享/订阅路由转发到它，其余 `/api` 请求转发到 runtime。

## 测试、准确率与趋势

```bash
# 772 个后端回归用例 + 前端 lint/build
./scripts/test-all.sh

# 对已激活的 TMS 仿真领域包执行多轮准确率/可用性评测
uv run python scripts/evaluate_queries.py \
  benchmarks/tms_sim_harness_cases.json \
  --output .local/evaluation/tms-sim.json
```

评测不会只看“请求成功”，还检查资产命中、追问时维度字段、血缘证据和延迟。CI 徽章、提交历史、Stars/Issues 徽章用于观察项目趋势；模型准确率必须绑定测试集、数据快照、模型和日期，不发布脱离环境的单一百分比。详见 [质量与评测](docs/quality.md)。

2026-07-16 的本地 TMS 仿真基线在 `deepseek-v4-flash` 上为 **15/15 checks**，各轮耗时 16.2–31.9 秒；该结果仅对应仓库内测试集、当时的数据与模型配置。

## 代码结构

```text
packages/contracts   Pydantic 契约、枚举、统一响应信封
services/semantic   语义目录、指标/Skill/报表和领域包仓储
services/runtime    Harness 规划、确定性执行、连接池、防护、血缘
services/export     导出、分享与订阅
apps/web            React 19 + Vite + Tailwind 管理与问数界面
```

依赖方向为 `contracts → semantic → runtime → web/export`。当前架构风险与拆分顺序见 [架构审计](docs/architecture-audit.md)。

## Roadmap

- 把 runtime API 和前端组合根按领域拆分，并补齐组件/E2E 测试。
- 将当前单节点 SQLite 交付队列扩展为可横向扩容的外部任务队列。
- 增加企业 SSO、细粒度 RBAC、密钥托管与多实例存储。
- 提供领域包注册表/市场和可复现的公开数据基准。
- 建立按版本、模型和数据快照聚合的质量/延迟趋势看板。

## 参与贡献

提交 Issue 时请附复现步骤、数据源类型、领域包/资产版本和脱敏后的 Harness trace。代码变更请先运行 `./scripts/test-all.sh`，并避免提交 `.env`、`.local` 或真实数据库凭据。

本项目采用 [Apache License 2.0](LICENSE)。
