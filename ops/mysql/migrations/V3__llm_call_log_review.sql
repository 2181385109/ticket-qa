-- 2026-09-25 LLM 提示词注入第二阶段(ADR-024):llm_call_log 记交叉校验 / 草稿输出检查的结论和规则的结论。
-- 只在已有数据卷上执行一次;新卷由 init/01-schema.sql 直接建出。
-- 用法(WSL 里):docker compose exec -T mysql mysql -uticketqa -pticketqa123 ticket_qa < /mnt/d/.../V3__llm_call_log_review.sql
SET NAMES utf8mb4;
USE ticket_qa;
ALTER TABLE llm_call_log
    MODIFY COLUMN degrade_reason VARCHAR(32) NULL COMMENT 'TIMEOUT / CIRCUIT_OPEN / UPSTREAM_ERROR / BAD_RESPONSE / UNSAFE_OUTPUT',
    ADD COLUMN needs_review  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '交叉校验冲突,已采用规则结果,待人工复核(ADR-024)' AFTER contract_violated,
    ADD COLUMN review_reason VARCHAR(64) NULL COMMENT 'ReviewReason 逗号连接:分类为冲突维度,草稿为输出检查命中类型' AFTER needs_review,
    ADD COLUMN rule_category VARCHAR(16) NULL COMMENT '关键词规则对同一文本的分类(离线评估替代阈值用)' AFTER review_reason,
    ADD COLUMN rule_priority VARCHAR(4)  NULL COMMENT '关键词规则对同一文本的优先级' AFTER rule_category;
