"""Judge input v3: section-aware trimming (app/eval/trim.py) and its version tag."""

import json

import pytest

from app.eval.judge import description_input, lead, pair_input
from app.eval.pairs import EvalPair, JobCard
from app.eval.profiles import load_profiles
from app.eval.trim import GAP, heading_kind, trim

FILLER = " ".join(["Our platform helps teams ship faster with reliable tooling."] * 12)


def posting() -> str:
    return "\n\n".join(
        [
            "About Acme",
            FILLER,  # company intro: boilerplate
            "What you'll do",
            "Build and run data pipelines. " * 10,
            "Benefits",
            "Health insurance, a learning budget and remote days. " * 6,
            "Requirements",
            "Python and SQL. 3-5 years of experience in data engineering.",
            "Equal opportunity",
            "We welcome everyone. " * 10,
        ]
    )


def test_short_descriptions_are_identical_to_v2() -> None:
    text = "Build pipelines. 2+ years of Python."
    assert trim(text, 3200) == text == lead(text)
    exact = "x" * 1400
    assert trim(exact, 3200) == lead(exact)


def test_headings_are_classified_and_about_you_is_not_boilerplate() -> None:
    assert heading_kind("Requirements:") == "requirements"
    assert heading_kind("About you") == "requirements"
    assert heading_kind("About the role") == "responsibilities"
    assert heading_kind("About Acme") == "boilerplate"
    assert heading_kind("Benefits") == "boilerplate"
    assert heading_kind(FILLER) is None


def test_requirements_survive_a_tight_cap_and_boilerplate_goes_first() -> None:
    text = posting()
    assert len(text) > 1400
    assert "3-5 years" not in lead(text)  # v2 cut it off
    out = trim(text, 600)
    assert "3-5 years of experience" in out
    assert "Requirements" in out
    assert "Health insurance" not in out and "We welcome everyone" not in out
    assert GAP in out
    assert len(out) <= 620
    # Kept paragraphs keep their original order.
    roomy = trim(text, 3200)
    assert roomy.index("What you'll do") < roomy.index("Requirements")


def test_an_experience_sentence_outside_the_requirements_is_kept() -> None:
    text = "\n\n".join(["Intro. " * 150, "You need 7+ years in backend systems.", "Misc. " * 150])
    out = trim(text, 800)
    assert "7+ years" in out


def test_label_records_the_input_version() -> None:
    profile = load_profiles()["p02"]
    job = JobCard(
        job_id="j1",
        title="NLP Engineer",
        company="Acme",
        source="greenhouse",
        location="Bengaluru",
        eligibility="IN",
        workplace="hybrid",
        employment="full_time",
        poster="employer",
        description=posting(),
    )
    pair = EvalPair(pair_id="p02:j1", profile_id="p02", job=job)
    v2 = json.loads(pair_input(profile, pair)[7:-8])["job"]["description"]
    v3 = json.loads(pair_input(profile, pair, 3)[7:-8])["job"]["description"]
    assert v2 == lead(posting())
    assert v3 == description_input(posting(), 3) and "3-5 years" in v3
    with pytest.raises(ValueError, match="unknown"):
        description_input("x", 9)
