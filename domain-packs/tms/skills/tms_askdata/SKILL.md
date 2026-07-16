---
name: tms-system-askdata
description: Use this skill when answering TMS logistics analytics questions over the TMS_ORACLE Oracle schema, generating controlled read-only SQL for project, shipping apply, shipping form, execution, receipt confirmation, carrier performance, and RFQ analysis.
---

# TMS System Askdata

Use this skill for natural-language ask-data requests against the `TMS_ORACLE` Oracle schema.

Workflow:

1. Classify the question into a TMS domain.
2. Pick the default fact table and default business time field.
3. Only use approved tables and approved joins.
4. Generate read-only Oracle SQL.
5. Return a structured JSON payload.

## Scope

Supported:

- 项目分析
- 发货申请分析
- 发货制单分析
- 发货执行分析
- 签收分析
- 承运商履约分析
- 询比价分析

Not supported in the first version:

- 运费结算
- 压车费用分析
- 利润分析
- 任意自由 SQL

## Primary tables

- `HR_PROJECT_BASE`
- `HR_DELIVER_APPLY`
- `HR_DELIVER_FORM`
- `HR_DELIVER_CARRY`
- `HR_RECEPIT_CONFIRM`
- `HR_SUPPLIER_INFO`
- `HR_TRANSPORT_DETAIL`
- `HR_DICT`

RFQ extension tables:

- `RFQ_PROJECT_BASE`
- `RFQ_ENQUIRY_INFO`
- `RFQ_SUPPLIER_INFO`
- `RFQ_TRANSPORT_DETAIL`

## Forbidden tables

Do not use:

- date-suffixed history tables such as `HR_DELIVER_FORM_20250901`
- temp tables such as `TEMP_HR_DELIVER_FORM`
- copy tables such as `HR_DELIVER_CARRY_WMS_COPY`
- clone tables such as `RFQ_TRANSPORT_DETAIL_A`

## Approved join path

- `HR_PROJECT_BASE.ID = HR_DELIVER_APPLY.PROJECT_ID`
- `HR_PROJECT_BASE.ID = HR_DELIVER_CARRY.PROJECT_ID`
- `HR_DELIVER_APPLY.APPLY_NO = HR_DELIVER_FORM.APPLY_NO`
- `HR_DELIVER_FORM.DELIVER_NO = HR_DELIVER_CARRY.DELIVER_NO`
- `HR_DELIVER_CARRY.DELIVER_NO = HR_RECEPIT_CONFIRM.DELIVER_NO`
- `HR_PROJECT_BASE.ID = HR_SUPPLIER_INFO.PROJECT_ID`
- `HR_PROJECT_BASE.ID = HR_TRANSPORT_DETAIL.PROJECT_ID`

Never invent joins. Never join on display names such as `PROJECT_NAME` or `CARRIER_NAME`.

## Metric rules

- 发货申请量: `count(distinct HR_DELIVER_APPLY.APPLY_NO)`
- 发货制单量: `count(distinct HR_DELIVER_FORM.DELIVER_NO)`
- 执行单量: `count(distinct HR_DELIVER_CARRY.DELIVER_NO)`
- 已签收量: `count(distinct HR_RECEPIT_CONFIRM.DELIVER_NO)`
- 完成量: first version uses `已签收量` as the default completion metric
- 运输中单量: `HR_DELIVER_CARRY.CAR_STATUS = '3'`
- 已卸货单量: `HR_DELIVER_CARRY.CAR_STATUS = '5'`
- 准时到货率: `ACTUAL_TIME <= PLAN_TIME`
- 承运商承运量: `count(distinct HR_DELIVER_FORM.DELIVER_NO)` grouped by `CARRIER_NAME`
- 询价单量: `count(distinct RFQ_ENQUIRY_INFO.ENQUIRY_NO)`
- 供应商报价次数: `count(*)` grouped by `RFQ_SUPPLIER_INFO.SUPPLIER_NAME`

## Time field rules

- 申请分析: default to `HR_DELIVER_APPLY.DELIVER_DATE`
- 制单分析: default to `HR_DELIVER_FORM.DELIVER_DATE`
- 执行分析: default to `HR_DELIVER_CARRY.DELIVER_DATE`
- 签收分析: default to `HR_RECEPIT_CONFIRM.HR_HANDLE_DATE`
- RFQ 分析: default to `RFQ_ENQUIRY_INFO.CREATED_TIME` or `RFQ_SUPPLIER_INFO.CREATED_TIME`

Use `CREATED_TIME` only if the user explicitly asks for creation time, except RFQ where it is the default business time.

## Status rules

Read [semantics.md](references/semantics.md) when you need field meanings, status maps, or table comments.

Read [test_cases.md](references/test_cases.md) when you need examples of supported questions and expected interpretations.

## Output format

Always return JSON with:

- `intent`
- `metrics`
- `dimensions`
- `time_range`
- `sql`
- `explanation`

## SQL rules

- Output only read-only `SELECT`
- Prefer explicit `JOIN`
- Prefer `count(distinct ...)` for business metrics
- Add a time filter unless the user explicitly asks for all-time data
- If the query is ranking-oriented, add a row limit
- Never use `select *`
