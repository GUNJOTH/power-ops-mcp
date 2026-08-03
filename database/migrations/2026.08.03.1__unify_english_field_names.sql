-- Unify MCP view column names with source-system English field names.
-- Does NOT modify vw_qa_work_order, vw_qa_defect, vw_qa_defect_fact or other
-- pre-existing shared views consumed by other workflows.
--
-- New MCP-specific views with short English column names matching user SQL:
--   vw_qa_work_order_mcp_fact   (row-level workorder with materials/tickets)
--   vw_qa_work_order_mcp        (deduplicated workorder)
--   vw_qa_workorder_equipment_mcp  (equipment lookup)

USE `sqldemo3`;

-- Row-level work order view with unified English field names.
CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_work_order_mcp_fact` AS
SELECT
  `工单号`                                        AS wonum,
  NULLIF(TRIM(`专业`), '')                          AS PROFESSION,
  NULLIF(TRIM(`专业描述`), '')                       AS specialty_name,
  `计划开始时间`                                     AS SCHEDSTART,
  `计划完成时间`                                     AS SCHEDFINISH,
  NULLIF(TRIM(`工单状态`), '')                       AS status,
  NULLIF(TRIM(`故障类别`), '')                       AS FAILURECODE,
  NULLIF(TRIM(`故障类型描述`), '')                    AS failure_category_name,
  NULLIF(TRIM(`故障问题`), '')                       AS PROBLEMCODE,
  NULLIF(TRIM(`故障问题描述`), '')                    AS failure_problem_name,
  NULLIF(TRIM(`故障原因`), '')                       AS FR1CODE,
  NULLIF(TRIM(`故障原因描述`), '')                    AS failure_cause_name,
  NULLIF(TRIM(`补救措施`), '')                       AS FR2CODE,
  NULLIF(TRIM(`补救措施描述`), '')                    AS remedy_name,
  NULLIF(TRIM(`检修班组编号`), '')                    AS teamnum,
  NULLIF(TRIM(`检修班组描述`), '')                    AS maintenance_team_name,
  NULLIF(TRIM(`工单描述`), '')                       AS DESCRIPTION,
  NULLIF(TRIM(`逻辑设备/KKS编码`), '')                AS LOCATION,
  NULLIF(TRIM(`逻辑设备/KKS描述`), '')                AS kks_name,
  NULLIF(TRIM(`资产/物理设备编码`), '')               AS ASSETNUM,
  NULLIF(TRIM(`资产/物料设备描述`), '')               AS equipment_name,
  NULLIF(TRIM(`物料编码`), '')                       AS itemnum,
  NULLIF(TRIM(`物料描述`), '')                       AS material_name,
  NULLIF(TRIM(`工作票编号`), '')                     AS work_ticket_code,
  NULLIF(TRIM(`工作票状态`), '')                     AS work_ticket_status,
  NULLIF(TRIM(`工作票内容`), '')                     AS work_ticket_content,
  NULLIF(TRIM(`检修交代`), '')                       AS maintenance_note
FROM `workorder`
WHERE NULLIF(TRIM(`工单号`), '') IS NOT NULL;

-- Deduplicated work order view (GROUP BY wonum, same semantics as vw_qa_work_order).
CREATE OR REPLACE ALGORITHM=TEMPTABLE SQL SECURITY DEFINER VIEW `vw_qa_work_order_mcp` AS
SELECT
  wonum,
  MAX(PROFESSION)            AS PROFESSION,
  MAX(specialty_name)        AS specialty_name,
  MIN(SCHEDSTART)            AS SCHEDSTART,
  MAX(SCHEDFINISH)           AS SCHEDFINISH,
  MAX(status)                AS status,
  MAX(FAILURECODE)           AS FAILURECODE,
  MAX(failure_category_name) AS failure_category_name,
  MAX(PROBLEMCODE)           AS PROBLEMCODE,
  MAX(failure_problem_name)  AS failure_problem_name,
  MAX(FR1CODE)               AS FR1CODE,
  MAX(failure_cause_name)    AS failure_cause_name,
  MAX(FR2CODE)               AS FR2CODE,
  MAX(remedy_name)           AS remedy_name,
  MAX(teamnum)               AS teamnum,
  MAX(maintenance_team_name) AS maintenance_team_name,
  MAX(DESCRIPTION)           AS DESCRIPTION,
  MAX(LOCATION)              AS LOCATION,
  MAX(kks_name)              AS kks_name,
  MAX(ASSETNUM)              AS ASSETNUM,
  MAX(equipment_name)        AS equipment_name,
  MAX(work_ticket_code)      AS work_ticket_code,
  MAX(work_ticket_status)    AS work_ticket_status
FROM `vw_qa_work_order_mcp_fact`
GROUP BY wonum;

-- Equipment lookup view for workorders.
CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_workorder_equipment_mcp` AS
SELECT
  `逻辑设备/KKS编码`          AS LOCATION,
  NULLIF(TRIM(`逻辑设备/KKS描述`), '') AS kks_name,
  `资产/物理设备编码`         AS ASSETNUM,
  NULLIF(TRIM(`资产/物料设备描述`), '') AS equipment_name,
  NULLIF(TRIM(`专业描述`), '') AS specialty_name
FROM `workorder`
WHERE `逻辑设备/KKS编码` IS NOT NULL OR `资产/物理设备编码` IS NOT NULL;

-- Equipment lookup view for defects.
CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_defect_equipment_mcp` AS
SELECT
  `KKS编码/位置`              AS LOCATION,
  NULLIF(TRIM(`位置描述`), '') AS location_name,
  `设备/资产编码`             AS assetnum,
  NULLIF(TRIM(`资产描述`), '') AS equipment_name,
  NULLIF(TRIM(`专业描述`), '') AS specialty_name
FROM `sr`
WHERE `KKS编码/位置` IS NOT NULL OR `设备/资产编码` IS NOT NULL;

INSERT INTO `mcp_schema_version` (`component`, `version`)
VALUES ('power_ops_views', '2026.08.03.1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = CURRENT_TIMESTAMP;
