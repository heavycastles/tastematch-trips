import os

# Keep unit tests offline even if a local .env was sourced into the shell.
os.environ["QLOO_FORCE_MOCK"] = "1"
for k in ("QLOO_API_KEY", "LLM_BASE_URL", "LLM_API_KEY"):
    os.environ.pop(k, None)
