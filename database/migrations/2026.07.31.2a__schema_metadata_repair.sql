-- Idempotent repair for environments whose import/cleanup process removes
-- MCP-owned metadata while preserving the governed views.

USE `sqldemo3`;

CREATE TABLE IF NOT EXISTS `mcp_schema_version` (
  `component` VARCHAR(100) NOT NULL,
  `version` VARCHAR(40) NOT NULL,
  `applied_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`component`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `mcp_schema_version` (`component`, `version`)
VALUES ('power_ops_views', '2026.07.31.2')
ON DUPLICATE KEY UPDATE `version` = VALUES(`version`), `applied_at` = CURRENT_TIMESTAMP;
