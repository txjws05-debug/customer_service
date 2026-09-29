-- 首次初始化 PostgreSQL 时自动执行：启用 pgvector 扩展。
-- 之后即可在客服项目里用它作为向量库（例如替代 Milvus）。
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
