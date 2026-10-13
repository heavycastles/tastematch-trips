from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import qloo
from .agent import plan

ROOT = Path(__file__).parent
app = FastAPI(title="TasteMatch Trips", version=(ROOT.parent / "VERSION").read_text().strip())


class Like(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = "movie"


class Traveler(BaseModel):
    label: str = Field(min_length=1, max_length=30, description="Nickname only; no personal data")
    likes: list[Like] = Field(min_length=1, max_length=8)


class PlanIn(BaseModel):
    travelers: list[Traveler] = Field(min_length=1, max_length=6)
    days: int = Field(2, ge=1, le=5)
    destination: str | None = Field(None, max_length=80)


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
        raise HTTPException(502, str(e)) from e


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
