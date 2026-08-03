-- Review with DBA and run only after import completion in a maintenance window.
-- These statements modify large raw tables and are intentionally separate.

USE `sqldemo3`;

ALTER TABLE `sr`
  ADD INDEX `idx_sr_qa_defect_code` (`缺陷编号`),
  ADD INDEX `idx_sr_qa_type_status_code` (`缺陷类别`, `缺陷状态`, `缺陷编号`),
  ADD INDEX `idx_sr_qa_specialty_code` (`专业描述`, `缺陷编号`),
  ADD INDEX `idx_sr_qa_kks_code` (`KKS编码/位置`(80), `缺陷编号`),
  ALGORITHM=INPLACE,
  LOCK=NONE;

ALTER TABLE `workorder`
  ADD INDEX `idx_workorder_qa_code` (`工单号`),
  ADD INDEX `idx_workorder_qa_start_status` (`计划开始时间`, `工单状态`),
  ADD INDEX `idx_workorder_qa_kks_code` (`逻辑设备/KKS编码`(80), `工单号`),
  ALGORITHM=INPLACE,
  LOCK=NONE;
