-- Incremental production upgrade for an existing sqldemo3 QA view deployment.
-- It intentionally does not replace vw_qa_defect_fact, vw_qa_defect or
-- vw_qa_work_order because those shared views expose compatibility columns
-- consumed by other workflows.

USE `sqldemo3`;

CREATE TABLE IF NOT EXISTS `mcp_schema_version` (
  `component` VARCHAR(100) NOT NULL,
  `version` VARCHAR(40) NOT NULL,
  `applied_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`component`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Row-level work-order view preserves multiple materials and work tickets.
CREATE OR REPLACE ALGORITHM=MERGE SQL SECURITY DEFINER VIEW `vw_qa_work_order_fact` AS
SELECT
  `工单号` AS workorder_code,
  NULLIF(TRIM(`专业`), '') AS specialty_code,
  NULLIF(TRIM(`专业描述`), '') AS specialty_name,
  `计划开始时间` AS planned_start_time,
  `计划完成时间` AS planned_finish_time,
  NULLIF(TRIM(`工单状态`), '') AS workorder_status,
  NULLIF(TRIM(`故障类别`), '') AS failure_category_code,
  NULLIF(TRIM(`故障类型描述`), '') AS failure_category_name,
  NULLIF(TRIM(`故障问题`), '') AS failure_problem_code,
  NULLIF(TRIM(`故障问题描述`), '') AS failure_problem_name,
  NULLIF(TRIM(`故障原因`), '') AS failure_cause_code,
  NULLIF(TRIM(`故障原因描述`), '') AS failure_cause_name,
  NULLIF(TRIM(`补救措施`), '') AS remedy_code,
  NULLIF(TRIM(`补救措施描述`), '') AS remedy_name,
  NULLIF(TRIM(`检修班组编号`), '') AS maintenance_team_code,
  NULLIF(TRIM(`检修班组描述`), '') AS maintenance_team_name,
  NULLIF(TRIM(`工单描述`), '') AS workorder_description,
  NULLIF(TRIM(`逻辑设备/KKS编码`), '') AS kks_code,
  NULLIF(TRIM(`逻辑设备/KKS描述`), '') AS kks_name,
  NULLIF(TRIM(`资产/物理设备编码`), '') AS asset_code,
  NULLIF(TRIM(`资产/物料设备描述`), '') AS equipment_name,
  NULLIF(TRIM(`物料编码`), '') AS material_code,
  NULLIF(TRIM(`物料描述`), '') AS material_name,
  NULLIF(TRIM(`工作票编号`), '') AS work_ticket_code,
  NULLIF(TRIM(`工作票状态`), '') AS work_ticket_status,
  NULLIF(TRIM(`工作票内容`), '') AS work_ticket_content,
  NULLIF(TRIM(`检修交代`), '') AS maintenance_note
FROM `workorder`
WHERE NULLIF(TRIM(`工单号`), '') IS NOT NULL;

INSERT INTO `mcp_schema_version` (`component`, `version`)
VALUES ('power_ops_views', '2026.07.31.1')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = CURRENT_TIMESTAMP;
