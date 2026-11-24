"""Board discovery helpers: reading board links, token guesses, the same-company check,
and writing companies_discovered.yaml. No network."""

from pathlib import Path

import yaml

from app.ingest.companies import load_companies
from app.ingest.discover import (
    Candidate,
    Verified,
    _domain_root,
    _token_variants,
    boards_in,
    merge_discovered,
    same_company,
)


def test_board_links_are_read_from_html() -> None:
    html = """
      <a href="https://boards.greenhouse.io/acme/jobs/123">Jobs</a>
      <a href="https://job-boards.greenhouse.io/acme">Jobs</a>
      <a href="https://jobs.lever.co/initech?team=eng">Lever</a>
      <a href="https://jobs.ashbyhq.com/Hooli">Ashby</a>
      <a href="https://apply.workable.com/piedpiper/">Workable</a>
      <a href="https://globex.recruitee.com/o/designer">Recruitee</a>
      <a href="https://jobs.smartrecruiters.com/Umbrella1/7434">SR</a>
      <a href="https://boards.greenhouse.io/embed/job_board?for=x">embed</a>
    """
    assert boards_in(html) == [
        ("greenhouse", "acme"),
        ("lever", "initech"),
        ("ashby", "Hooli"),  # Ashby tokens are case-sensitive
        ("smartrecruiters", "umbrella1"),
        ("workable", "piedpiper"),
        ("recruitee", "globex"),
    ]


def test_token_guesses_from_slug_name_and_domain() -> None:
    assert _token_variants("bolna", "Bolna AI", _domain_root("https://bolna.ai")) == [
        "bolna",
        "bolna-ai",
        "bolnaai",
    ]
    assert _domain_root("https://www.careers.acme.io/jobs") == "acme"


def verified(board_name: str | None, text: str = "") -> Verified:
    return Verified("X", "ashby", "x", 3, 1, 0, board_name, text=text)


def test_guessed_board_must_be_the_same_company() -> None:
    apollo = Candidate("Apollo", website="https://www.apollofirst.xyz/")
    # Lever / Ashby name nobody: the company's domain must appear in the postings.
    assert not same_company(verified(None, "apollo.io is the leading sales platform"), apollo)
    ok = verified(None, "apply at apollofirst.xyz/careers")
    assert same_company(ok, apollo) and ok.name_check == "domain_in_postings"
    assert not same_company(verified(None, "anything"), Candidate("Apollo"))  # no website
    # Boards that name their company: names must match.
    assert same_company(verified("Bolna"), Candidate("Bolna AI", website="https://bolna.ai"))
    assert not same_company(verified("Apollo.io"), apollo)


def test_merge_writes_a_loadable_file_and_skips_known_boards(tmp_path: Path) -> None:
    path = tmp_path / "companies_discovered.yaml"
    accepted = [
        (
            Candidate(
                "Bolna AI",
                website="https://bolna.ai",
                yc_batch="Fall 2025",
                industries=["b2b"],
                discovered_via="yc-oss",
            ),
            Verified("Bolna AI", "ashby", "bolna", 5, 5, 0, None, "domain_in_postings"),
        ),
        (  # already in companies.yaml: skipped
            Candidate("Anthropic", discovered_via="yc-oss"),
            Verified("Anthropic", "greenhouse", "anthropic", 9, 1, 1, "Anthropic", "matched"),
        ),
    ]
    assert merge_discovered(accepted, path) == 1
    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["companies"][0]
    assert entry["yc_batch"] == "Fall 2025" and entry["verified"]["india_eligible"] == 5
    loaded = {e.name: e for e in load_companies(discovered_path=path)}
    assert loaded["Bolna AI"].ats == "ashby" and loaded["Bolna AI"].discovered_via == "yc-oss"
    assert merge_discovered(accepted, path) == 0  # idempotent
