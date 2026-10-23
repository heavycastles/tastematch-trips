from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from . import qloo
from .agent import plan

ROOT = Path(__file__).parent
app = FastAPI(title="TasteMatch Trips", version=(ROOT.parent / "VERSION").read_text().strip())


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class Like(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = "movie"
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


FIELD_HINTS = {"travelers": "Add 1–6 travelers, each with a nickname and at least one favourite.",
               "likes": "Every traveler needs at least one favourite (up to 8).",
               "label": "Every traveler needs a nickname (up to 30 characters).",
               "name": "Favourites can't be empty (up to 100 characters).",
               "days": "Trips can be 1 to 5 days long.",
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


@app.get("/healthz")
def healthz():
    return {"ok": True, "qloo": "live" if qloo.live() else "mock"}


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


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
