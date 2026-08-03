-- Index-friendly lookup views for equipment resolution.
-- KKS and asset codes are direct aliases so predicates can be pushed to the
-- existing raw-table indexes. Display fields may still be normalized.

USE `sqldemo3`;

CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_defect_equipment_lookup` AS
SELECT
  `KKS编码/位置` AS kks_code,
  NULLIF(TRIM(`位置描述`), '') AS location_name,
  `设备/资产编码` AS asset_code,
  NULLIF(TRIM(`资产描述`), '') AS equipment_name,
  NULLIF(TRIM(`专业描述`), '') AS specialty_name
FROM `sr`
WHERE `KKS编码/位置` IS NOT NULL OR `设备/资产编码` IS NOT NULL;

CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_workorder_equipment_lookup` AS
SELECT
  `逻辑设备/KKS编码` AS kks_code,
  NULLIF(TRIM(`逻辑设备/KKS描述`), '') AS kks_name,
  `资产/物理设备编码` AS asset_code,
  NULLIF(TRIM(`资产/物料设备描述`), '') AS equipment_name,
  NULLIF(TRIM(`专业描述`), '') AS specialty_name
FROM `workorder`
WHERE `逻辑设备/KKS编码` IS NOT NULL OR `资产/物理设备编码` IS NOT NULL;

INSERT INTO `mcp_schema_version` (`component`, `version`)
VALUES ('power_ops_views', '2026.07.31.2')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = CURRENT_TIMESTAMP;
