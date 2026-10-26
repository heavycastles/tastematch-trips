from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from . import qloo
from .agent import plan

ROOT = Path(__file__).parent
VERSION = (ROOT.parent / "VERSION").read_text().strip()
app = FastAPI(title="TasteMatch Trips", version=VERSION)
# Vercel's edge compresses on its own; this covers the Docker / Render deploys (the page is ~53 KB raw, ~18 KB gzipped).
app.add_middleware(GZipMiddleware, minimum_size=1024)


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class Like(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field("movie", max_length=20)
    _s = field_validator("name", mode="before")(_strip)


class Traveler(BaseModel):
    label: str = Field(min_length=1, max_length=30, description="Nickname only; no personal data")
    likes: list[Like] = Field(min_length=1, max_length=8)
    _s = field_validator("label", mode="before")(_strip)


class PlanIn(BaseModel):
    travelers: list[Traveler] = Field(min_length=1, max_length=6)
    days: int = Field(2, ge=1, le=5)
    destination: str | None = Field(None, max_length=80)

    @field_validator("destination", mode="before")
    @classmethod
    def _blank_dest(cls, v):
        v = _strip(v)
        return v or None

    @model_validator(mode="after")
    def _unique_labels(self):
        seen = [t.label.casefold() for t in self.travelers]
        if len(seen) != len(set(seen)):
            raise ValueError("Each traveler needs a different nickname.")
        return self


SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                    "Referrer-Policy": "strict-origin-when-cross-origin"}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


FIELD_HINTS = {"travelers": "Add 1–6 travelers, each with a nickname and at least one favourite.",
               "likes": "Every traveler needs at least one favourite (up to 8).",
               "label": "Every traveler needs a nickname (up to 30 characters).",
               "name": "Each favourite needs a name of 1–100 characters.",
               "days": "Trips can be 1 to 5 days long.",
               "type": "Each favourite's type must be one of the listed options (movie, artist, brand, …).",
               "destination": "Destination is limited to 80 characters."}


@app.exception_handler(RequestValidationError)
async def _friendly_422(request: Request, exc: RequestValidationError):
    msgs = []
    for err in exc.errors():
        custom = str(err.get("msg", "")).removeprefix("Value error, ")
        field = next((str(x) for x in reversed(err.get("loc", ())) if isinstance(x, str) and x in FIELD_HINTS), None)
        m = custom if err.get("type") == "value_error" else FIELD_HINTS.get(field, "Please check the form.")
        if m not in msgs:
            msgs.append(m)
    return JSONResponse(status_code=422, content={"error": "invalid_input", "ask": " ".join(msgs)})


QLOO_ERRORS = {
    "rate_limited": (503, "Qloo is rate-limiting requests right now. Please wait ~30 seconds and try again."),
    "qloo_timeout": (504, "Qloo took too long to answer. Please try again in a moment."),
    "bad_location": (502, "Qloo couldn't resolve that location. Try a larger nearby city."),
    "upstream": (502, "Qloo returned an unexpected error. Please try again in a moment."),
}


SAMPLE = {"days": 2, "travelers": [
    {"label": "Aziz", "likes": [{"name": "Spirited Away", "type": "movie"}, {"name": "Patagonia", "type": "brand"}]},
    {"label": "Malika", "likes": [{"name": "Daft Punk", "type": "artist"}, {"name": "Wes Anderson", "type": "person"}]},
    {"label": "Rustam", "likes": [{"name": "Anthony Bourdain", "type": "person"},
                                  {"name": "Chef's Table", "type": "tv_show"}]}]}


@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return {"ok": True, "qloo": "live" if qloo.live() else "mock"}


def _commit() -> str:
    """Short commit of the running build: GIT_COMMIT (set at deploy time), Vercel's git SHA, else "unknown"."""
    sha = (os.getenv("GIT_COMMIT") or os.getenv("VERCEL_GIT_COMMIT_SHA") or "").strip()
    return sha[:7] if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha) else "unknown"


@app.api_route("/version", methods=["GET", "HEAD"])
def version():
    """Which build is live, so a judge (or a deploy check) can match the hosted demo to a commit in the repo."""
    return {"version": VERSION, "commit": _commit(), "qloo": "live" if qloo.live() else "mock"}


@app.get("/api/sample")
def sample():
    return SAMPLE


@app.post("/api/plan")
def api_plan(body: PlanIn):
    try:
        return plan(body.model_dump()["travelers"], body.days, body.destination)
    except qloo.QlooError as e:
        code, ask = QLOO_ERRORS.get(e.kind, QLOO_ERRORS["upstream"])
        return JSONResponse(status_code=code, content={"error": e.kind if e.kind in QLOO_ERRORS else "upstream",
                                                       "ask": ask})


# The page is static: let the CDN keep it (s-maxage) so first paint doesn't wait for a cold Python function.
# Browsers still revalidate every load (max-age=0), and a redeploy purges the Vercel edge cache.
INDEX_CACHE = "public, max-age=0, s-maxage=600, stale-while-revalidate=86400"


@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": INDEX_CACHE})
