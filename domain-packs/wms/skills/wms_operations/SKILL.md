---
name: wms-operations-askdata
description: Use this skill for controlled read-only WMS delivery, warehouse, material, shipment, outbound, and customer analytics on the TMS_ORACLE Oracle schema.
---

# WMS Operations Askdata

Only query `WMS_DELIVERY_INFO`, `HR_DELIVER_APPLY_WMS`, `WMS_LOGISTICS_INFO`, and `ORG_WMS`.
Generate a single read-only Oracle `SELECT`; never write data and never use backup, copy, temporary, or date-suffixed tables.

Primary grains:

- Delivery: `WMS_DELIVERY_INFO.ID`
- Material: `HR_DELIVER_APPLY_WMS.WL_CODE`
- Shipment: `WMS_LOGISTICS_INFO.SHIP_NUM`
- Outbound: `WMS_LOGISTICS_INFO.OUT_NUM`
- Warehouse: `ORG_WMS.WMS_ID`

Use `WMS_DELIVERY_INFO.DELIVERY_DATE` for delivery time and
`WMS_LOGISTICS_INFO.SHIP_DATE` for outbound time. Join warehouse metadata only
with `WMS_DELIVERY_INFO.WMS_ID = ORG_WMS.WMS_ID`. Do not invent joins.
