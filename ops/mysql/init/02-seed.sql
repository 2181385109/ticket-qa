-- 种子数据:6 个坐席,覆盖三种角色、两个组。密码不存在——鉴权只认 X-User-Id 头。
SET NAMES utf8mb4;   -- 每个 init 文件是独立的 mysql 客户端会话,不写这一行中文会按 latin1 双重编码
USE ticket_qa;

INSERT INTO agent (id, username, display_name, role, group_id, active, created_at, updated_at) VALUES
    (1, 'admin',    '管理员',   'ADMIN',  1, 1, NOW(3), NOW(3)),
    (2, 'leader_1', '一组组长', 'LEADER', 1, 1, NOW(3), NOW(3)),
    (3, 'agent_a',  '坐席A',    'AGENT',  1, 1, NOW(3), NOW(3)),
    (4, 'agent_b',  '坐席B',    'AGENT',  1, 1, NOW(3), NOW(3)),
    (5, 'leader_2', '二组组长', 'LEADER', 2, 1, NOW(3), NOW(3)),
    (6, 'agent_c',  '坐席C',    'AGENT',  2, 1, NOW(3), NOW(3));
