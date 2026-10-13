"""Container entrypoint (the runtime image has no shell, so read PORT here)."""

import os

import uvicorn

from app.qloo import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))  # noqa: S104
