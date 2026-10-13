import os

for k in ("QLOO_API_KEY", "LLM_BASE_URL", "LLM_API_KEY"):
    os.environ.pop(k, None)
