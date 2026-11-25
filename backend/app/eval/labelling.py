"""The labelling tool: a single local page, keyboard-driven.

    python -m app.eval.cli label --set <name>      (make label SET=<name>)

Keys: 0 1 2 3 = grade, S = skip, U or Backspace = undo, R = show the rubric.
Every key press is written to eval/labels/<set>/human.jsonl and fsynced before the next
pair appears (app/eval/labels.py). Stop at any time; start again to resume.
Local only: it binds to 127.0.0.1 unless told otherwise, and has no login.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.eval.judge import rubric_text
from app.eval.labels import LabelSession
from app.eval.pairs import load_judge, load_pairs
from app.eval.profiles import EvalProfile, load_profiles

_PAGE = Path(__file__).resolve().parent / "static" / "label.html"


class LabelBody(BaseModel):
    pair_id: str
    label: int = Field(ge=0, le=3)


class SkipBody(BaseModel):
    pair_id: str


def open_session(folder: Path, *, blind_size: int) -> LabelSession:
    pairs = load_pairs(folder / "pairs.jsonl")
    if not pairs:
        raise SystemExit(f"no pairs in {folder / 'pairs.jsonl'}")
    return LabelSession(folder, pairs, load_judge(folder / "judge.jsonl"), blind_size=blind_size)


def _profile_view(p: EvalProfile) -> dict[str, Any]:
    prefs = p.profile.preferences
    return {
        "id": p.id,
        "lives_in": p.lives_in,
        "experience": f"{p.experience_band} ({p.profile.years_experience} yrs)",
        "field": p.field,
        "persona": p.persona,
        "query": p.query,
        "skills": p.profile.skills,
        "workplace": prefs.workplace or ["any"],
        "countries": prefs.countries,
        "seniority": prefs.seniority or ["any"],
        "dealbreakers": p.dealbreakers(),
        "a_3_looks_like": p.judge_notes.a_3_looks_like,
        "rules_out": p.judge_notes.rules_out,
    }


def create_app(session: LabelSession, profiles: dict[str, EvalProfile] | None = None) -> FastAPI:
    profiles = profiles if profiles is not None else load_profiles()
    rubric = rubric_text()
    app = FastAPI(title="JobMatch eval labelling", docs_url=None, redoc_url=None)

    def state() -> dict[str, Any]:
        pid = session.current()
        body: dict[str, Any] = {
            "progress": session.progress(),
            "rubric": rubric,
            "set": session.folder.name,
        }
        if pid is None:
            return {**body, "done": True}
        pair = session.pairs[pid]
        entry = session.state.entries.get(pid)
        suggestion = None
        if session.shows_suggestion(pid):
            record = session.judge[pid]
            suggestion = {
                "label": record.label,
                "reason": record.reason,
                "confidence": record.confidence,
            }
        return {
            **body,
            "done": False,
            "pair_id": pid,
            "phase": session.phase_of(pid),
            "previously_skipped": entry is not None and entry.kind == "skip",
            "profile": _profile_view(profiles[pair.profile_id]),
            "job": pair.job.model_dump(),
            "suggestion": suggestion,
        }

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return state()

    @app.post("/api/label")
    def post_label(body: LabelBody) -> dict[str, Any]:
        try:
            session.label(body.pair_id, body.label)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return state()

    @app.post("/api/skip")
    def post_skip(body: SkipBody) -> dict[str, Any]:
        try:
            session.skip(body.pair_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return state()

    @app.post("/api/undo")
    def post_undo() -> dict[str, Any]:
        session.undo()
        return state()

    return app
