-- 2026-09-21 抢单竞态修复(ADR-016 / ADR-017):ticket 表加乐观锁版本号。
-- 只在已有数据卷上执行一次;新卷由 init/01-schema.sql 直接建出带 version 的表。
-- 用法(WSL 里):docker compose exec -T mysql mysql -uticketqa -pticketqa123 ticket_qa < /mnt/d/.../V2__ticket_version.sql
SET NAMES utf8mb4;
USE ticket_qa;
ALTER TABLE ticket
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号,每次成功写入 +1(ADR-016)' AFTER closed_at;
