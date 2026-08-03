USE `sqldemo3`;

-- Contract version
SELECT component, version, applied_at
FROM mcp_schema_version
WHERE component = 'power_ops_views';

-- Business-key uniqueness
SELECT COUNT(*) AS rows_total, COUNT(DISTINCT defect_code) AS distinct_keys
FROM vw_qa_defect;
SELECT COUNT(*) AS rows_total, COUNT(DISTINCT workorder_code) AS distinct_keys
FROM vw_qa_work_order;

-- Required identifiers must not be null in governed views
SELECT COUNT(*) AS invalid_rows FROM vw_qa_defect WHERE defect_code IS NULL;
SELECT COUNT(*) AS invalid_rows FROM vw_qa_work_order WHERE workorder_code IS NULL;

-- Explain baselines must be reviewed after every migration/index change
EXPLAIN SELECT defect_type_name, COUNT(DISTINCT defect_code)
FROM vw_qa_defect_fact GROUP BY defect_type_name;
EXPLAIN SELECT workorder_status, COUNT(DISTINCT workorder_code)
FROM vw_qa_work_order GROUP BY workorder_status;
