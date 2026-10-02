"""测试运行前的环境准备。

ws.config.config 在**导入时**就实例化 `Settings`，而它有若干必填项
（LLM_API_KEY、DATABASE_URL 等）。CI 里既没有 .env 也没有这些变量，
任何 import 到 config 的测试都会直接 ValidationError。

这里统一补一份测试用占位值。os.environ 的优先级高于 .env，
所以本地和 CI 行为一致，而且不会真的去连这些地址。
"""

import os

_TEST_ENV = {
    "LLM_API_KEY": "test-key",
    "LLM_MODEL": "test-model",
    "LLM_BASE_URL": "https://example.invalid/v1",
    "DATABASE_URL": "postgresql+asyncpg://cs:cs@127.0.0.1:5432/customer_service",
    "COMMERCE_API_BASE_URL": "http://127.0.0.1:18081",
    "APP_HOST": "127.0.0.1",
    "APP_PORT": "18082",
}

for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)
