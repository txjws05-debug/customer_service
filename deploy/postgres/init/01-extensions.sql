-- 首次初始化 PostgreSQL 时自动执行：启用 pgvector 扩展。
-- 之后即可用 PostgreSQL 直接充当向量库（可替代 Milvus / Qdrant）。
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
