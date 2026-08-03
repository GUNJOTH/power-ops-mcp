-- Publish the semantic contract only after mcp_defect_current has been built
-- and its row-count/uniqueness checks have passed.

USE `sqldemo3`;

INSERT INTO `mcp_schema_version` (`component`, `version`)
SELECT 'power_ops_views', '2026.07.31.3'
WHERE EXISTS (
  SELECT 1 FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mcp_defect_current'
)
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = CURRENT_TIMESTAMP;
