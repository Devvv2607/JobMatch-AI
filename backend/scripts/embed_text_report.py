"""What boilerplate stripping did to the embedding input, measured with the model's own
tokenizer (no truncation, so the full lengths are counted).

    python -m scripts.embed_text_report [--examples 5] [--seed 3]

Covers every non-expired job whose search_text has been prepared. "Before" is the
version-1 card (title, level, skills, full description); "after" is the current card.
Prints markdown.
"""

import argparse
import random
import statistics
from pathlib import Path

from sqlalchemy import create_engine, text
from tokenizers import Tokenizer

from app.core.config import get_settings
from app.ingest.boilerplate import paragraphs
from app.ingest.embed import EMBED_TEXT_VERSION, job_card
from app.ml.embedder import MAX_TOKENS


def card_v1(title: str, seniority: str, skills: list[str], description: str) -> str:
    skill_line = f"Skills: {', '.join(skills)}\n" if skills else ""
    return f"{title}\nLevel: {seniority}\n{skill_line}{description}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.embed_text_report")
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()

    settings = get_settings()
    tokenizer = Tokenizer.from_file(str(Path(settings.embedding_model_dir) / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()

    def tokens(texts: list[str]) -> list[int]:
        return [len(e.ids) for e in tokenizer.encode_batch(texts)]

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
            SELECT j.id, j.title, j.seniority, j.skills, j.location, j.description,
                   j.search_text, c.name AS company
            FROM jobs j JOIN companies c ON c.id = j.company_id
            WHERE j.status != 'expired' AND j.search_text IS NOT NULL
            ORDER BY j.id
            """)
        ).all()
    engine.dispose()

    desc_before: list[int] = []
    desc_after: list[int] = []
    card_before: list[int] = []
    card_after: list[int] = []
    for start in range(0, len(rows), 256):
        chunk = rows[start : start + 256]
        desc_before += tokens([r.description for r in chunk])
        desc_after += tokens([r.search_text for r in chunk])
        card_before += tokens(
            [card_v1(r.title, r.seniority, r.skills, r.description) for r in chunk]
        )
        card_after += tokens(
            [job_card(r.title, r.seniority, r.skills, r.location, r.search_text) for r in chunk]
        )
    removed = [b - a for b, a in zip(desc_before, desc_after, strict=True)]
    n = len(rows)
    over = MAX_TOKENS

    print(f"# Embedding text, recipe v1 -> v{EMBED_TEXT_VERSION}\n")
    print(f"Jobs: {n} (non-expired, prepared). Token counts use the bge-small tokenizer,")
    print("untruncated, and include the [CLS]/[SEP] tokens.\n")
    print("| Measure | Before (v1) | After |\n|---|---|---|")
    print(
        f"| Description tokens, mean | {statistics.mean(desc_before):.0f} "
        f"| {statistics.mean(desc_after):.0f} |"
    )
    print(
        f"| Description tokens, median | {statistics.median(desc_before):.0f} "
        f"| {statistics.median(desc_after):.0f} |"
    )
    print(
        f"| Card tokens, mean | {statistics.mean(card_before):.0f} "
        f"| {statistics.mean(card_after):.0f} |"
    )
    print(
        f"| Cards longer than {over} tokens (truncated) | "
        f"{sum(t > over for t in card_before)} ({sum(t > over for t in card_before) / n:.0%}) | "
        f"{sum(t > over for t in card_after)} ({sum(t > over for t in card_after) / n:.0%}) |"
    )
    print(
        f"\nTokens removed per job: mean {statistics.mean(removed):.0f}, "
        f"median {statistics.median(removed):.0f}; "
        f"jobs with nothing removed: {sum(r == 0 for r in removed)}; "
        f"jobs left with an empty description: {sum(a <= 2 for a in desc_after)}.\n"
    )

    stripped = [i for i, r in enumerate(removed) if r > 0]
    rng = random.Random(args.seed)  # noqa: S311 -- reproducible sample
    picks = rng.sample(stripped, min(args.examples, len(stripped)))
    for number, i in enumerate(picks, 1):
        r = rows[i]
        kept = set(paragraphs(r.search_text))
        dropped = [p for p in paragraphs(r.description) if p not in kept]
        print(f"## Example {number}: {r.title} ({r.company})\n")
        print(f"Description tokens: {desc_before[i]} before, {desc_after[i]} after.\n")
        print(f"Removed ({len(dropped)} paragraphs):\n")
        for p in dropped[:12]:
            line = " ".join(p.split())
            print(f"- ~~{line[:110]}{'…' if len(line) > 110 else ''}~~")
        if len(dropped) > 12:
            print(f"- … {len(dropped) - 12} more")
        after = " ".join(r.search_text.split())
        print(f"\nKept (start): {after[:400]}{'…' if len(after) > 400 else ''}\n")


if __name__ == "__main__":
    main()
