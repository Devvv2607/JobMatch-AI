"""Human labels: an append-only event log (human.jsonl) and a fixed labelling order
(plan.json).

Every key press is one event, appended and fsynced before the tool shows the next pair,
so a crash or a closed tab loses nothing; restarting replays the log (resume). Undo is an
event too, so the log is a full history.

Order (brief, item 5):
1. BLIND: `blind_size` pairs stratified by source x employment x poster, shown WITHOUT
   the judge's label. Weighted kappa is computed on these only. No suggestion is shown
   for any pair until every blind pair has a label: skipped blind pairs come back
   (oldest skip first) before the second phase starts.
2. SUGGESTED: every other pair, with the judge's label shown, judge-uncertain first
   (confidence low, then medium, then high; within each, grades 1 and 2 before 0 and 3).

label_source per pair: human_blind (labelled in the blind phase), human_with_suggestion
(labelled with the judge's label on screen), human_no_suggestion (labelled in the second
phase when the pair had no judge label yet), llm_only (judge label, no human label).
"""

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.eval.pairs import EvalPair, JudgeRecord, append_jsonl, read_jsonl

Phase = Literal["blind", "suggested"]
LabelSource = Literal["human_blind", "human_with_suggestion", "human_no_suggestion", "llm_only"]
_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


class Plan(BaseModel):
    seed: int
    blind: list[str]
    suggested: list[str]
    created_at: str


class Event(BaseModel):
    at: str
    event: Literal["label", "skip", "undo"]
    pair_id: str | None = None
    label: int | None = Field(default=None, ge=0, le=3)
    phase: Phase | None = None
    shown_suggestion: bool = False


@dataclass(frozen=True)
class Entry:
    kind: Literal["label", "skip"]
    label: int | None
    phase: Phase
    shown_suggestion: bool
    seq: int  # position in the log, so skipped pairs come back oldest skip first

    @property
    def source(self) -> LabelSource:
        if self.phase == "blind":
            return "human_blind"
        return "human_with_suggestion" if self.shown_suggestion else "human_no_suggestion"


def stratified_sample(pairs: Sequence[EvalPair], size: int, seed: int) -> list[str]:
    """`size` pair ids spread over strata (source x employment x poster): proportional
    allocation with at least one per stratum while the budget lasts, then random."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible order, not security
    strata: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for p in pairs:
        key = (p.job.source, p.job.employment, p.job.poster)
        strata[key].append(p.pair_id)
    for ids in strata.values():
        rng.shuffle(ids)
    size = min(size, len(pairs))
    keys = sorted(strata, key=lambda k: (-len(strata[k]), k))
    take = {k: 0 for k in keys}
    for k in keys[:size]:  # one each, largest strata first
        take[k] = 1
    remaining = size - sum(take.values())
    total = len(pairs)
    for k in keys:  # then proportionally (floor)
        extra = min(len(strata[k]) - take[k], int(remaining * len(strata[k]) / total))
        take[k] += max(extra, 0)
    leftover = [i for k in keys for i in strata[k][take[k] :]]
    rng.shuffle(leftover)
    chosen = [i for k in keys for i in strata[k][: take[k]]]
    chosen += leftover[: size - len(chosen)]
    rng.shuffle(chosen)
    return chosen


def suggested_order(
    pairs: Sequence[EvalPair], exclude: set[str], judge: dict[str, JudgeRecord], seed: int
) -> list[str]:
    rng = random.Random(seed + 1)  # noqa: S311 - a reproducible order, not security
    rest = [p.pair_id for p in pairs if p.pair_id not in exclude]
    rng.shuffle(rest)  # the tie-break within a group

    def key(pid: str) -> tuple[int, int]:
        record = judge.get(pid)
        if record is None:
            return (3, 0)  # unjudged pairs last
        boundary = 0 if record.label in (1, 2) else 1
        return (_CONFIDENCE_ORDER[record.confidence], boundary)

    return sorted(rest, key=key)  # stable: keeps the shuffled order within a group


def make_plan(
    pairs: Sequence[EvalPair], judge: dict[str, JudgeRecord], *, blind_size: int, seed: int
) -> Plan:
    blind = stratified_sample(pairs, blind_size, seed)
    return Plan(
        seed=seed,
        blind=blind,
        suggested=suggested_order(pairs, set(blind), judge, seed),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def load_or_create_plan(
    folder: Path, pairs: Sequence[EvalPair], judge: dict[str, JudgeRecord], *, blind_size: int
) -> Plan:
    """The plan is written once and reused, so the order survives restarts. Pairs added
    to pairs.jsonl later are appended to the suggested phase."""
    path = folder / "plan.json"
    if path.exists():
        plan = Plan.model_validate_json(path.read_text(encoding="utf-8"))
        known = set(plan.blind) | set(plan.suggested)
        new = [p for p in pairs if p.pair_id not in known]
        if new:
            plan.suggested += suggested_order(new, set(), judge, plan.seed)
            path.write_text(plan.model_dump_json(indent=1), encoding="utf-8")
        return plan
    plan = make_plan(pairs, judge, blind_size=blind_size, seed=20261125)
    path.write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    return plan


@dataclass
class LabelState:
    """The replayed log: the current entry per pair and the undo stack."""

    entries: dict[str, Entry] = field(default_factory=dict)
    undo_stack: list[tuple[str, Entry | None]] = field(default_factory=list)
    events: int = 0

    def apply(self, event: Event) -> str | None:
        """Applies one event; returns the pair an undo reopened."""
        self.events += 1
        if event.event == "undo":
            if not self.undo_stack:
                return None
            pid, previous = self.undo_stack.pop()
            if previous is None:
                self.entries.pop(pid, None)
            else:
                self.entries[pid] = previous
            return pid
        if event.pair_id is None or event.phase is None:
            raise ValueError(f"{event.event} event without a pair or phase")
        self.undo_stack.append((event.pair_id, self.entries.get(event.pair_id)))
        self.entries[event.pair_id] = Entry(
            kind=event.event,
            label=event.label,
            phase=event.phase,
            shown_suggestion=event.shown_suggestion,
            seq=self.events,
        )
        return None

    def labelled(self) -> dict[str, Entry]:
        return {pid: e for pid, e in self.entries.items() if e.kind == "label"}


class LabelSession:
    """Owns one label set folder: plan, log, and what to show next."""

    def __init__(
        self,
        folder: Path,
        pairs: Sequence[EvalPair],
        judge: dict[str, JudgeRecord],
        *,
        blind_size: int,
    ) -> None:
        self.folder = folder
        self.pairs = {p.pair_id: p for p in pairs}
        self.judge = judge
        self.plan = load_or_create_plan(folder, pairs, judge, blind_size=blind_size)
        self.log = folder / "human.jsonl"
        self.state = LabelState()
        self.reopened: str | None = None  # the pair an undo brought back, shown next
        for raw in read_jsonl(self.log):
            self.state.apply(Event.model_validate(raw))

    def phase_of(self, pid: str) -> Phase:
        return "blind" if pid in set(self.plan.blind) else "suggested"

    def blind_done(self) -> bool:
        labelled = self.state.labelled()
        return all(pid in labelled for pid in self.plan.blind)

    def current(self) -> str | None:
        """The pair to show: the one an undo reopened, else the first unlabelled pair in
        plan order (blind phase first; skipped pairs return at the end of their phase)."""
        entries = self.state.entries
        if self.reopened is not None:
            entry = entries.get(self.reopened)
            if entry is None or entry.kind == "skip":
                return self.reopened
        for phase_ids in (self.plan.blind, self.plan.suggested):
            fresh = [pid for pid in phase_ids if pid not in entries]
            if fresh:
                return fresh[0]
            skipped = [pid for pid in phase_ids if entries[pid].kind == "skip"]
            if skipped:
                return min(skipped, key=lambda pid: entries[pid].seq)
        return None

    def shows_suggestion(self, pid: str) -> bool:
        return self.phase_of(pid) == "suggested" and self.blind_done() and pid in self.judge

    def _append(self, event: Event) -> str | None:
        append_jsonl(self.log, event)  # fsynced before the state changes
        return self.state.apply(event)

    def label(self, pid: str, value: int) -> None:
        self._check(pid)
        self.reopened = None
        self._append(
            Event(
                at=_now(),
                event="label",
                pair_id=pid,
                label=value,
                phase=self.phase_of(pid),
                shown_suggestion=self.shows_suggestion(pid),
            )
        )

    def skip(self, pid: str) -> None:
        self._check(pid)
        self.reopened = None
        self._append(Event(at=_now(), event="skip", pair_id=pid, phase=self.phase_of(pid)))

    def undo(self) -> str | None:
        """Takes back the last label or skip; that pair is shown next."""
        self.reopened = self._append(Event(at=_now(), event="undo"))
        return self.reopened

    def _check(self, pid: str) -> None:
        if pid != self.current():
            raise ValueError("that pair is not the one on screen (reload the page)")

    def progress(self) -> dict[str, int]:
        labelled = self.state.labelled()
        skipped = sum(e.kind == "skip" for e in self.state.entries.values())
        return {
            "blind_done": sum(pid in labelled for pid in self.plan.blind),
            "blind_total": len(self.plan.blind),
            "done": len(labelled),
            "total": len(self.pairs),
            "skipped": skipped,
            "events": self.state.events,
        }


def label_sources(
    pairs: Sequence[EvalPair], judge: dict[str, JudgeRecord], log: Path
) -> dict[str, tuple[int, LabelSource]]:
    """The final grade and its source per pair: the human label when there is one,
    else the judge's (llm_only). Pairs with neither are left out."""
    state = LabelState()
    for raw in read_jsonl(log):
        state.apply(Event.model_validate(raw))
    out: dict[str, tuple[int, LabelSource]] = {}
    labelled = state.labelled()
    for p in pairs:
        entry = labelled.get(p.pair_id)
        if entry is not None and entry.label is not None:
            out[p.pair_id] = (entry.label, entry.source)
        elif p.pair_id in judge:
            out[p.pair_id] = (judge[p.pair_id].label, "llm_only")
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
