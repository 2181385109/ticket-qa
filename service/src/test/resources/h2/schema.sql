-- H2(MySQL 兼容模式)下的精简建表,只给 @MybatisPlusTest 切片用(ADR-013)。
-- 与 ops/mysql/init/01-schema.sql 的差别:去掉 UNSIGNED / COMMENT / ENGINE / CHARSET 这些 H2 不认或无意义的修饰,
-- 列名、类型语义、唯一键保持一致——切片测的是 TicketMapper 里两条手写 SQL 和去重表唯一键,不是 DDL 本身。
CREATE TABLE IF NOT EXISTS ticket (
    id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ticket_no     VARCHAR(32)  NOT NULL,
    title         VARCHAR(200) NOT NULL,
    content       TEXT         NOT NULL,
    category      VARCHAR(16)  NOT NULL,
    priority      VARCHAR(4)   NOT NULL,
    status        VARCHAR(16)  NOT NULL,
    customer_id   BIGINT       NOT NULL,
    group_id      BIGINT       NOT NULL,
    assignee_id   BIGINT       NULL,
    created_by    BIGINT       NULL,
    sla_deadline  TIMESTAMP(3) NOT NULL,
    escalated_at  TIMESTAMP(3) NULL,
    closed_at     TIMESTAMP(3) NULL,
    version       INT          NOT NULL DEFAULT 0,
    deleted       TINYINT      NOT NULL DEFAULT 0,
    created_at    TIMESTAMP(3) NOT NULL,
    updated_at    TIMESTAMP(3) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_ticket_no ON ticket (ticket_no);
CREATE INDEX IF NOT EXISTS idx_ticket_status_sla ON ticket (status, sla_deadline);

CREATE TABLE IF NOT EXISTS mq_message_dedup (
    id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    message_id   VARCHAR(64)  NOT NULL,
    consumer     VARCHAR(64)  NOT NULL,
    event_type   VARCHAR(32)  NOT NULL,
    ticket_id    BIGINT       NULL,
    trace_id     VARCHAR(64)  NULL,
    consumed_at  TIMESTAMP(3) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_dedup_message_consumer ON mq_message_dedup (message_id, consumer);
