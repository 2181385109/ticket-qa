-- =====================================================================
-- 智能客服工单系统 · 建表 DDL(MySQL 8, utf8mb4)
-- 由 mysql 官方镜像在首次初始化时自动执行(挂载到 /docker-entrypoint-initdb.d)。
-- 索引设计的决策记录见 docs/adr/ADR-005-索引设计.md,这里只写"是什么"。
-- =====================================================================

SET NAMES utf8mb4;
USE ticket_qa;

-- ---------------------------------------------------------------------
-- 坐席表:系统里的操作者。鉴权简化为 X-User-Id 头 → 查此表得到角色/组。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)     NOT NULL COMMENT '登录名,唯一',
    display_name  VARCHAR(64)     NOT NULL COMMENT '显示名',
    role          VARCHAR(16)     NOT NULL COMMENT 'AGENT / LEADER / ADMIN',
    group_id      BIGINT UNSIGNED NOT NULL COMMENT '所属客服组',
    active        TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '1 在职 0 停用',
    created_at    DATETIME(3)     NOT NULL,
    updated_at    DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_agent_username (username),
    KEY idx_agent_group (group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='坐席';

-- ---------------------------------------------------------------------
-- 工单表:核心业务表。
-- status 是状态机的当前状态;sla_deadline 在创建时按优先级算好,
-- 让 SLA 扫描是一次纯索引范围查询而不是逐行算时间。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ticket_no     VARCHAR(32)     NOT NULL COMMENT '业务单号,对外暴露',
    title         VARCHAR(200)    NOT NULL,
    content       TEXT            NOT NULL,
    category      VARCHAR(16)     NOT NULL COMMENT 'BILLING / TECH / REFUND / OTHER',
    priority      VARCHAR(4)      NOT NULL COMMENT 'P0 / P1 / P2',
    status        VARCHAR(16)     NOT NULL COMMENT '状态机当前状态',
    customer_id   BIGINT UNSIGNED NOT NULL COMMENT '提单客户',
    group_id      BIGINT UNSIGNED NOT NULL COMMENT '归属客服组',
    assignee_id   BIGINT UNSIGNED NULL     COMMENT '当前处理坐席,PENDING 时为空',
    created_by    BIGINT UNSIGNED NULL     COMMENT '创建操作者(坐席代建时有值)',
    sla_deadline  DATETIME(3)     NOT NULL COMMENT '响应截止 = created_at + 优先级时限',
    escalated_at  DATETIME(3)     NULL     COMMENT '首次自动升级时间;非空即表示已升级过',
    closed_at     DATETIME(3)     NULL     COMMENT '最近一次关闭时间,重开 7 天窗口的依据',
    version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本号,每次成功写入 +1(ADR-016)',
    deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '逻辑删除',
    created_at    DATETIME(3)     NOT NULL,
    updated_at    DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ticket_no (ticket_no),
    KEY idx_ticket_status_sla (status, sla_deadline),
    KEY idx_ticket_assignee_status (assignee_id, status),
    KEY idx_ticket_group_status_created (group_id, status, created_at),
    KEY idx_ticket_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单';

-- ---------------------------------------------------------------------
-- 审计日志:每次状态变更一条,谁 / 何时 / 从哪到哪 / 来源。
-- 只追加不修改,是数据一致性校验的依据。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_audit_log (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ticket_id      BIGINT UNSIGNED NOT NULL,
    from_status    VARCHAR(16)     NULL     COMMENT '创建时为空',
    to_status      VARCHAR(16)     NOT NULL,
    operator_id    BIGINT UNSIGNED NULL     COMMENT '定时任务触发时为空',
    operator_name  VARCHAR(64)     NOT NULL COMMENT '人名或 SCHEDULER / LLM',
    source         VARCHAR(16)     NOT NULL COMMENT 'MANUAL / SCHEDULER / LLM',
    remark         VARCHAR(500)    NULL,
    trace_id       VARCHAR(64)     NULL,
    created_at     DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_audit_ticket_created (ticket_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单状态变更审计';

-- ---------------------------------------------------------------------
-- 消息去重表:MQ 消费端幂等。
-- (message_id, consumer) 唯一;插入成功才处理业务,重复投递直接跳过。
-- 与业务写操作在同一个本地事务里,业务失败则去重记录一起回滚。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mq_message_dedup (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    message_id   VARCHAR(64)     NOT NULL COMMENT '生产端生成的 UUID',
    consumer     VARCHAR(64)     NOT NULL COMMENT '消费者标识,同一消息可被不同消费者各处理一次',
    event_type   VARCHAR(32)     NOT NULL,
    ticket_id    BIGINT UNSIGNED NULL,
    trace_id     VARCHAR(64)     NULL,
    consumed_at  DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_dedup_message_consumer (message_id, consumer),
    KEY idx_dedup_ticket (ticket_id),
    KEY idx_dedup_consumed_at (consumed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='MQ 消费去重';

-- ---------------------------------------------------------------------
-- LLM 调用记录:每次调用一条,含请求/响应模型名、耗时、是否降级、原因。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_call_log (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ticket_id       BIGINT UNSIGNED NULL,
    scene           VARCHAR(16)     NOT NULL COMMENT 'CLASSIFY / DRAFT_REPLY',
    request_model   VARCHAR(64)     NOT NULL COMMENT '配置里请求的模型名',
    response_model  VARCHAR(64)     NULL     COMMENT '响应体里回报的模型名,降级时为空',
    latency_ms      INT UNSIGNED    NOT NULL,
    degraded        TINYINT(1)      NOT NULL DEFAULT 0,
    degrade_reason  VARCHAR(32)     NULL     COMMENT 'TIMEOUT / CIRCUIT_OPEN / UPSTREAM_ERROR / BAD_RESPONSE',
    raw_category    VARCHAR(64)     NULL     COMMENT 'LLM 原始返回的分类(可能越界)',
    final_category  VARCHAR(16)     NULL     COMMENT '最终落库的分类',
    contract_violated TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '返回值越出枚举',
    trace_id        VARCHAR(64)     NULL,
    created_at      DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_llm_ticket (ticket_id),
    KEY idx_llm_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LLM 调用记录';

-- ---------------------------------------------------------------------
-- 附件表:文件落本地目录,文件名重命名为 UUID,原始名只记录在这里。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticket_attachment (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ticket_id      BIGINT UNSIGNED NOT NULL,
    original_name  VARCHAR(255)    NOT NULL,
    stored_name    VARCHAR(64)     NOT NULL COMMENT 'UUID + 扩展名',
    ext            VARCHAR(8)      NOT NULL,
    mime_type      VARCHAR(64)     NOT NULL COMMENT '按魔数识别出的真实类型',
    size_bytes     BIGINT UNSIGNED NOT NULL,
    uploaded_by    BIGINT UNSIGNED NOT NULL,
    created_at     DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_attachment_stored_name (stored_name),
    KEY idx_attachment_ticket (ticket_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单附件';
