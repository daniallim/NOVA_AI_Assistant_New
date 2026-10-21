-- ============================================================
--  NOVA AI Assistant - MySQL schema
--  Run this in MySQL Workbench, or let setup_database.py do it.
-- ============================================================

CREATE DATABASE IF NOT EXISTS nova_ai
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE nova_ai;

-- ------------------------------------------------------------
-- users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    email       VARCHAR(190)  NOT NULL,
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- conversations
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT           NOT NULL,
    title       VARCHAR(255)  NOT NULL DEFAULT 'New conversation',
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_conversations_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    KEY idx_conversations_user (user_id, created_at)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- messages
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id  INT   NOT NULL,
    role             ENUM('user','assistant','system','tool') NOT NULL,
    content          MEDIUMTEXT NOT NULL,
    created_at       DATETIME   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_messages_conversation
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ON DELETE CASCADE,
    KEY idx_messages_conversation (conversation_id, id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- memories
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id      INT        NOT NULL,
    memory_type  ENUM('fact','preference','skill','event','system') NOT NULL DEFAULT 'fact',
    content      TEXT       NOT NULL,
    importance   TINYINT    NOT NULL DEFAULT 5,
    created_at   DATETIME   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_memories_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_memories_importance CHECK (importance BETWEEN 1 AND 10),
    KEY idx_memories_ranked (user_id, importance DESC, id DESC)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- tasks
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_name   VARCHAR(255) NOT NULL,
    status      ENUM('pending','running','done','failed') NOT NULL DEFAULT 'pending',
    result      TEXT         NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_tasks_status (status, id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- tool_logs
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tool_logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    tool_name   VARCHAR(100) NOT NULL,
    argument    TEXT         NULL,
    result      MEDIUMTEXT   NULL,
    status      ENUM('success','error','blocked') NOT NULL DEFAULT 'success',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_tool_logs_name (tool_name, id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- Convenience view: full chat transcript with user names
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_chat_history AS
SELECT
    m.id            AS message_id,
    u.name          AS user_name,
    c.id            AS conversation_id,
    c.title         AS conversation_title,
    m.role,
    m.content,
    m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN users u         ON u.id = c.user_id
ORDER BY m.id;
