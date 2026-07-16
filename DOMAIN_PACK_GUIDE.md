# SQ-BI 领域包开发指南

> 本指南以接入 **MES（制造执行系统）** 数据为例，手把手说明如何为 SQ-BI 引擎创建并注册一个新的领域包。

---

## 概念速览

SQ-BI 引擎本身不绑定任何业务领域。所有业务知识（表结构、指标定义、问数 Skill）都封装在**领域包（Domain Pack）**里，引擎在启动时动态加载。

```
SQ-BI 引擎（通用）
  ├── domain-packs/tms/     ← TMS 领域包（已内置）
  ├── domain-packs/mes/     ← 你要创建的 MES 领域包
  └── domain-packs/wms/     ← 未来的 WMS 领域包
```

每个领域包是一个目录，包含：

| 文件 | 作用 |
|------|------|
| `pack.yaml` | 包清单：ID、名称、版本、资产列表 |
| `semantic/*.yaml` | 语义目录：数据源、表、字段、指标、同义词 |
| `skills/*/SKILL.md` | 问数 Skill：告诉 LLM 如何把问题转为 SQL |

---

## 第一步：创建目录结构

```bash
mkdir -p domain-packs/mes/semantic
mkdir -p domain-packs/mes/skills/mes_askdata/references
```

最终结构：

```
domain-packs/mes/
├── pack.yaml
├── semantic/
│   └── mes_semantic.yaml
└── skills/
    └── mes_askdata/
        ├── SKILL.md
        └── references/
            ├── semantics.md   # 表/字段速查手册（给 LLM 的参考）
            └── test_cases.md  # 推荐问句示例
```

---

## 第二步：编写 `pack.yaml`（包清单）

```yaml
# domain-packs/mes/pack.yaml
pack_id: mes
namespace: mes
name: MES 制造执行系统领域包
version: "1.0.0"
description: >
  MES 领域包，覆盖工单管理、工序追踪、设备OEE、质检、
  物料消耗等核心 MES 业务场景。
author: your-team
min_engine_version: "1.0.0"
tags: ["mes", "manufacturing", "production"]

assets:
  - asset_type: semantic
    path: semantic/mes_semantic.yaml
    description: MES 数据库语义目录

  - asset_type: skill
    path: skills/mes_askdata/SKILL.md
    description: MES 自然语言问数 Skill

dependencies: []
```

**字段说明：**
- `pack_id`：全局唯一，字母+下划线，例如 `mes`
- `namespace`：SQL 名称空间前缀，避免多包指标名冲突
- `assets`：每个资产的 `path` 是相对于包目录的路径

---

## 第三步：编写语义目录 `mes_semantic.yaml`

语义目录告诉引擎："这个数据库里有哪些表、哪些字段、什么含义"。

```yaml
# domain-packs/mes/semantic/mes_semantic.yaml

data_sources:
  - data_source_id: "oracle_mes"
    name: "MES Oracle 生产库"
    database_type: "oracle"           # oracle | mysql | postgres | clickhouse
    connection_alias: "PROD_MES"      # 与 config.yaml 的 db.dsn 对应
    is_read_only: true
    owner: "admin"
    description: "生产执行系统主库"
    tags: ["production", "mes"]

tables:
  # ── 工单主表 ──────────────────────────────────────────────
  - table_id: "mes_work_order"
    data_source_id: "oracle_mes"
    physical_name: "MES_WORK_ORDER"
    business_name: "工单表"
    description: "生产工单主数据，记录计划数量、实际数量、开工/完工时间"
    owner: "admin"
    tags: ["fact", "production"]
    columns:
      - column_id: "wo_id"
        physical_name: "WO_ID"
        business_name: "工单ID"
        data_type: "VARCHAR2"
        is_primary_key: true
      - column_id: "product_code"
        physical_name: "PRODUCT_CODE"
        business_name: "产品编码"
        data_type: "VARCHAR2"
      - column_id: "plan_qty"
        physical_name: "PLAN_QTY"
        business_name: "计划数量"
        data_type: "NUMBER"
      - column_id: "actual_qty"
        physical_name: "ACTUAL_QTY"
        business_name: "实际产量"
        data_type: "NUMBER"
      - column_id: "start_time"
        physical_name: "START_TIME"
        business_name: "开工时间"
        data_type: "DATE"
        is_default_time_field: true
      - column_id: "end_time"
        physical_name: "END_TIME"
        business_name: "完工时间"
        data_type: "DATE"
      - column_id: "status"
        physical_name: "STATUS"
        business_name: "工单状态"
        data_type: "VARCHAR2"
        # 0=待开工 1=生产中 2=已完工 3=已关闭

  # ── 设备OEE表 ─────────────────────────────────────────────
  - table_id: "mes_equipment_oee"
    data_source_id: "oracle_mes"
    physical_name: "MES_EQUIPMENT_OEE"
    business_name: "设备OEE记录表"
    description: "按天记录每台设备的可用率、性能率、质量率和综合OEE"
    owner: "admin"
    tags: ["fact", "equipment"]
    columns:
      - column_id: "oee_id"
        physical_name: "OEE_ID"
        business_name: "OEE记录ID"
        data_type: "NUMBER"
        is_primary_key: true
      - column_id: "equipment_code"
        physical_name: "EQUIPMENT_CODE"
        business_name: "设备编码"
        data_type: "VARCHAR2"
      - column_id: "stat_date"
        physical_name: "STAT_DATE"
        business_name: "统计日期"
        data_type: "DATE"
        is_default_time_field: true
      - column_id: "availability"
        physical_name: "AVAILABILITY"
        business_name: "可用率"
        data_type: "NUMBER"
        description: "0-1 小数，可用时间/计划时间"
      - column_id: "performance"
        physical_name: "PERFORMANCE"
        business_name: "性能率"
        data_type: "NUMBER"
      - column_id: "quality"
        physical_name: "QUALITY"
        business_name: "质量率"
        data_type: "NUMBER"
      - column_id: "oee"
        physical_name: "OEE"
        business_name: "综合OEE"
        data_type: "NUMBER"

  # ── 质检记录表 ────────────────────────────────────────────
  - table_id: "mes_quality_check"
    data_source_id: "oracle_mes"
    physical_name: "MES_QUALITY_CHECK"
    business_name: "质检记录表"
    description: "记录每批次产品的抽检数量、合格数量、不良原因"
    owner: "admin"
    tags: ["fact", "quality"]
    columns:
      - column_id: "check_id"
        physical_name: "CHECK_ID"
        business_name: "质检ID"
        data_type: "NUMBER"
        is_primary_key: true
      - column_id: "wo_id"
        physical_name: "WO_ID"
        business_name: "工单ID"
        data_type: "VARCHAR2"
      - column_id: "check_date"
        physical_name: "CHECK_DATE"
        business_name: "检验日期"
        data_type: "DATE"
        is_default_time_field: true
      - column_id: "check_qty"
        physical_name: "CHECK_QTY"
        business_name: "抽检数量"
        data_type: "NUMBER"
      - column_id: "pass_qty"
        physical_name: "PASS_QTY"
        business_name: "合格数量"
        data_type: "NUMBER"
      - column_id: "defect_reason"
        physical_name: "DEFECT_REASON"
        business_name: "不良原因"
        data_type: "VARCHAR2"

# ── 指标定义 ──────────────────────────────────────────────────
metrics:
  - metric_id: "mes_production_yield"
    metric_code: "production_yield"
    name: "生产良品率"
    description: "本期合格产出 / 本期计划产量"
    data_source_id: "oracle_mes"
    formula:
      expression: >
        SELECT
          ROUND(SUM(PASS_QTY) * 100.0 / NULLIF(SUM(CHECK_QTY), 0), 2) AS production_yield
        FROM MES_QUALITY_CHECK
        WHERE CHECK_DATE BETWEEN :start_date AND :end_date
    unit: "%"
    tags: ["quality", "kpi"]

  - metric_id: "mes_avg_oee"
    metric_code: "avg_oee"
    name: "平均综合OEE"
    description: "统计周期内所有设备 OEE 均值"
    data_source_id: "oracle_mes"
    formula:
      expression: >
        SELECT ROUND(AVG(OEE) * 100, 2) AS avg_oee
        FROM MES_EQUIPMENT_OEE
        WHERE STAT_DATE BETWEEN :start_date AND :end_date
    unit: "%"
    tags: ["equipment", "kpi"]

# ── 同义词 ────────────────────────────────────────────────────
synonyms:
  - term: "工单"
    mappings: ["MES_WORK_ORDER", "WO_ID"]
  - term: "OEE"
    mappings: ["MES_EQUIPMENT_OEE", "oee"]
  - term: "良品率"
    mappings: ["production_yield", "PASS_QTY", "CHECK_QTY"]
  - term: "质检"
    mappings: ["MES_QUALITY_CHECK"]
  - term: "设备"
    mappings: ["MES_EQUIPMENT_OEE", "EQUIPMENT_CODE"]
```

**关键规则：**
- `physical_name` 必须和数据库里的真实表名/列名**完全一致**（大小写按你的库）
- `is_default_time_field: true` 标记时间筛选的默认列，引擎据此生成 `WHERE` 子句
- `is_primary_key: true` 帮助引擎理解表关系，用于 JOIN 推断
- `metrics.formula.expression` 里的 `:start_date` / `:end_date` 是引擎自动注入的参数

---

## 第四步：编写问数 Skill `SKILL.md`

Skill 是一段给 LLM 看的"工作说明书"，格式固定，内容完全由你控制。

```markdown
---
name: mes-askdata
description: >
  Use this skill when answering MES production analytics questions over the
  PROD_MES Oracle schema, covering work orders, equipment OEE, quality
  inspection, and material consumption analysis.
---

# MES System Askdata

Use this skill for natural-language ask-data requests against the `PROD_MES` Oracle schema.

## Workflow

1. Classify the question into a MES domain (production / equipment / quality).
2. Pick the default fact table and default time field.
3. Only use approved tables and approved joins.
4. Generate read-only Oracle SQL with FETCH FIRST N ROWS ONLY.
5. Return a structured JSON payload.

## Scope

Supported:
- 工单产量分析
- 设备OEE分析
- 质检良品率分析
- 产线效率对比

Not supported:
- 成本核算
- BOM 展开
- 自由 SQL

## Primary tables

| 物理表名 | 业务含义 | 默认时间字段 |
|---------|---------|------------|
| `MES_WORK_ORDER` | 工单主数据 | `START_TIME` |
| `MES_EQUIPMENT_OEE` | 设备OEE日报 | `STAT_DATE` |
| `MES_QUALITY_CHECK` | 质检记录 | `CHECK_DATE` |

## Approved JOINs

```sql
-- 工单 + 质检
MES_WORK_ORDER wo
JOIN MES_QUALITY_CHECK qc ON wo.WO_ID = qc.WO_ID
```

## Output format

Return JSON with keys: `question`, `sql`, `display_columns`, `metric_code` (optional).

## Examples

**Q: 本月生产良品率是多少？**
```sql
SELECT ROUND(SUM(PASS_QTY)*100.0/NULLIF(SUM(CHECK_QTY),0),2) AS 良品率
FROM MES_QUALITY_CHECK
WHERE CHECK_DATE >= TRUNC(SYSDATE, 'MM')
  AND CHECK_DATE < ADD_MONTHS(TRUNC(SYSDATE,'MM'),1)
FETCH FIRST 1 ROWS ONLY
```

**Q: 本周各设备平均OEE排名？**
```sql
SELECT EQUIPMENT_CODE AS 设备编码, ROUND(AVG(OEE)*100,2) AS 平均OEE
FROM MES_EQUIPMENT_OEE
WHERE STAT_DATE >= TRUNC(SYSDATE,'IW')
GROUP BY EQUIPMENT_CODE
ORDER BY 平均OEE DESC
FETCH FIRST 20 ROWS ONLY
```
```

**编写 Skill 的三条准则：**
1. `description` 字段（frontmatter）决定引擎**何时路由到这个 Skill**，写清楚场景范围
2. `Approved JOINs` 必须明确——这是防止 LLM 随意 JOIN 错表的最重要约束
3. `Examples` 至少提供 3-5 个覆盖不同难度的 SQL 样例

---

## 第五步：注册到配置文件

编辑 `config.yaml`，把 MES 包目录加入 `packs`：

```yaml
# config.yaml
packs:
  - path: domain-packs/tms     # 已有的 TMS 包
  - path: domain-packs/mes     # 新增 MES 包
```

或通过环境变量：

```bash
export SQ_BI_ENABLED_PACKS="tms,mes"
```

---

## 第六步：验证

### 6.1 语法验证

```bash
# 验证 pack.yaml 能被正确加载
uv run python - <<'EOF'
from sq_bi_runtime.pack_loader import install_pack, get_registry
result = install_pack("domain-packs/mes")
print(f"加载结果: {result}")
print(f"语义文件: {get_registry().get_semantic_catalog_paths()}")
EOF
```

### 6.2 单元测试

创建 `domain-packs/mes/tests/test_mes_pack.py`：

```python
from pathlib import Path
from sq_bi_runtime.pack_loader import install_pack, PackRegistry, load_manifest

MES_PACK_DIR = Path(__file__).parent.parent

def test_pack_loads_cleanly() -> None:
    manifest = load_manifest(MES_PACK_DIR)
    assert manifest.pack_id == "mes"
    assert manifest.namespace == "mes"

def test_semantic_paths_resolved() -> None:
    registry = PackRegistry()
    manifest = load_manifest(MES_PACK_DIR)
    registry.install(manifest, MES_PACK_DIR)
    paths = registry.get_semantic_catalog_paths()
    assert len(paths) == 1
    assert paths[0].exists()

def test_skill_asset_declared() -> None:
    manifest = load_manifest(MES_PACK_DIR)
    skill_assets = [a for a in manifest.assets if a.asset_type == "skill"]
    assert len(skill_assets) >= 1
```

```bash
uv run pytest domain-packs/mes/tests/ -v
```

### 6.3 冒烟测试（需要数据库连接）

```bash
# 启动服务后问一个 MES 问题
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "本月生产良品率是多少？", "data_source_id": "oracle_mes"}'
```

---

## 常见问题

**Q: 表名大小写要注意什么？**

`physical_name` 的大小写必须和你的数据库一致。Oracle 默认存储为大写，所以写 `MES_WORK_ORDER` 而不是 `mes_work_order`。MySQL/PostgreSQL 一般小写。

**Q: 两个包里有同名指标怎么办？**

引擎按 `namespace` 隔离，TMS 包的指标是 `tms.production_count`，MES 包的是 `mes.production_count`，不会冲突。问数时引擎根据 `data_source_id` 路由到正确的包。

**Q: 可以跨包 JOIN 吗？**

暂不支持跨数据源 JOIN。如果 MES 和 TMS 在同一个数据库实例下，可以在 Skill 的 `Approved JOINs` 里声明跨 schema 的 JOIN（`MES_SCHEMA.TABLE` 格式），但两个包的语义目录需要各自声明所涉及的表。

**Q: MES 的时间字段不是 DATE 类型而是 VARCHAR 怎么办？**

在列定义里加 `data_type: "VARCHAR2"`，然后在 Skill 的 Examples 里教 LLM 用 `TO_DATE(START_TIME, 'YYYY-MM-DD')` 转换。

**Q: 上线后想修改语义，会影响已有历史？**

不会。语义目录只影响新的问数请求；已经执行过的 SQL 记录在审计日志里，不会被回溯修改。

---

## 参考结构（TMS 包作为完整示例）

```
domain-packs/tms/
├── pack.yaml                              ← 包清单
├── semantic/
│   └── tms_semantic.yaml                 ← 1409 行，覆盖 15 张表 + 20+ 指标
└── skills/
    └── tms_askdata/
        ├── SKILL.md                       ← 问数工作说明书
        └── references/
            ├── semantics.md              ← 表/字段速查（辅助 LLM）
            └── test_cases.md             ← 推荐问句 30+
```

按这个结构仿写 MES 包，引擎即可无缝加载。
