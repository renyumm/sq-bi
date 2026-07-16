# TMS 语义参考

## 表注释

- `HR_DELIVER_APPLY`: 发货申请表
- `HR_DELIVER_FORM`: 发货制单
- `HR_DELIVER_CARRY`: 发货执行
- `HR_RECEPIT_CONFIRM`: 签收确认
- `HR_SUPPLIER_INFO`: 供方信息
- `HR_TRANSPORT_DETAIL`: 项目运输明细

## 关键字段

### HR_DELIVER_APPLY

- `APPLY_NO`: 申请编号
- `PROJECT_ID`: 项目ID
- `DELIVER_DATE`: 发货日期
- `DELIVER_NO`: 发货单号
- `POWER`: 功率(W)
- `TRANSPORT_TYPE`: 提货方式
- `STATUS`: 状态

说明：

- 申请层统计默认以 `APPLY_NO` 为粒度

### HR_DELIVER_FORM

- `DELIVER_NO`: 发货单号
- `APPLY_NO`: 申请编号
- `PROJECT_ID`: 项目ID
- `DELIVER_DATE`: 发货日期
- `CARRIER_NAME`: 承运商名称
- `TRANSPORT_TYPE`: 运输方式
- `STATUS`: 状态

### HR_DELIVER_CARRY

- `DELIVER_NO`: 申请单号/执行关联号
- `APPLY_NO`: 申请编号
- `PROJECT_ID`: 项目ID
- `CAR_STATUS`: 车辆状态
- `PLAN_TIME`: 计划到货时间
- `ACTUAL_TIME`: 实际到货时间
- `STATUS`: `0=申请, 1=制单, 2=执行`
- `DELIVER_DATE`: 发货日期

### HR_RECEPIT_CONFIRM

- `DELIVER_NO`: 申请单号
- `STATUS`: 状态
- `HR_HANDLE_DATE`: 环睿处理时间
- `HS_HANDLE_DATE`: 环晟处理时间

首版确认：

- 默认以 `已签收` 作为“完成”口径
- 默认以 `HR_HANDLE_DATE` 作为签收分析时间字段

## 字典映射

### 运输方式 `HR_DICT.TYPE = 2`

- `1`: 公路运输
- `2`: 公铁联运
- `3`: 其他

### 车辆状态 `HR_DICT.TYPE = 6`

- `0`: 未到厂
- `1`: 已到厂
- `2`: 装货离厂
- `3`: 运输途中
- `4`: 已到目的地
- `5`: 已卸货
- `6`: 已叫号
- `7`: 待进厂
- `8`: 已入厂
- `9`: 已退车
- `10`: 装货中
- `11`: 待离厂
- `12`: 异常

## RFQ 首版纳入范围

- `RFQ_ENQUIRY_INFO`: 询价主单分析
- `RFQ_SUPPLIER_INFO`: 供应商报价次数分析
