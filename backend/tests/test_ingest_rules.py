"""Normalisation rules: eligibility, skills, seniority, salary, text, companies."""

import pytest

from app.ingest.companies import company_slug, load_companies
from app.ingest.countries import country_code, gazetteer
from app.ingest.eligibility import (
    UNKNOWN,
    WorkLocation,
    from_description,
    parse_location,
    work_location,
)
from app.ingest.normalise import content_hash, normalise
from app.ingest.salary import Salary, from_structured, from_text, fx_table, to_annual_usd
from app.ingest.seniority import employment_type, seniority_from_title
from app.ingest.skills import canonical_skill, extract_skills
from app.ingest.text import html_to_text, normalise_key, normalise_title
from app.ingest.types import RawPosting, RawSalary


def posting(**overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": "greenhouse",
        "source_id": "1",
        "company_name": "Acme",
        "title": "Software Engineer",
        "source_url": "https://example.com/jobs/1",
        "description_html": "<p>Build things.</p>",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


# --- location parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "scope", "countries"),
    [
        ("Mumbai, India", "listed", {"IN"}),
        ("Bangalore, IN", "listed", {"IN"}),
        ("hyderabad", "listed", {"IN"}),
        ("tamil nadu", "listed", {"IN"}),
        ("San Francisco, CA | Seattle, WA", "listed", {"US"}),
        ("Austin, TX", "listed", {"US"}),
        ("US - Remote", "listed", {"US"}),
        ("Remote (U.S.)", "listed", {"US"}),
        ("USA, Canada, USA timezones", "listed", {"US", "CA"}),
        (
            "London, UK; Ontario, CAN; Remote-Friendly, United States; San Francisco, CA",
            "listed",
            {"GB", "CA", "US"},
        ),
        ("Home Based - APAC", "listed", None),  # APAC includes India
        ("Remote (EMEA)", "listed", None),
        ("Worldwide", "worldwide", set()),
        ("Anywhere", "worldwide", set()),
        ("Remote - Global", "worldwide", set()),
        ("Berlin / Remote", "listed", {"DE"}),
        ("Remote, IST timezone", "listed", {"IN"}),
    ],
)
def test_parse_location(text: str, scope: str, countries: set[str] | None) -> None:
    parsed = parse_location(text)
    assert parsed is not None
    assert parsed[0] == scope
    if countries is not None:
        assert set(parsed[1]) == countries


def test_region_membership_decides_india_eligibility() -> None:
    apac = parse_location("Home Based - APAC")
    emea = parse_location("Remote (EMEA)")
    assert apac is not None and "IN" in apac[1]
    assert emea is not None and "IN" not in emea[1]


# Added 2026-11-21 from the top unknown locations in the live pool.
@pytest.mark.parametrize(
    ("text", "countries"),
    [
        ("Kuwait City, Kuwait", {"KW"}),
        ("Istanbul, Türkiye", {"TR"}),
        ("Hong Kong SAR", {"HK"}),
        ("Kazakhstan", {"KZ"}),
        ("Malmö", {"SE"}),
        ("Johannesburg", {"ZA"}),
        ("Bahrain", {"BH"}),
        ("Jordan", {"JO"}),
        ("Seychelles", {"SC"}),
        ("El Salvador (Remote)", {"SV"}),
        ("CDMX", {"MX"}),
        ("South San Francisco", {"US"}),
        ("Remote - Washington D.C.", {"US"}),  # the trailing dot is stripped before lookup
        ("Remote - US East", {"US"}),
        ("Western US", {"US"}),
        ("California Remote", {"US"}),
        ("Texas Remote", {"US"}),
        ("Singapore Office", {"SG"}),
        ("United States & EMEA", None),
        ("IN-Bengaluru", {"IN"}),
        ("MX- Mexico City", {"MX"}),
        ("CA-Toronto; CA-Remote", {"CA"}),
        ("Cluj-Napoca", {"RO"}),  # a hyphenated city is not read as code + place
        ("Northeast Asia (Remote)", {"JP", "KR", "CN", "HK", "TW"}),
    ],
)
def test_places_added_from_the_unknown_report(text: str, countries: set[str] | None) -> None:
    parsed = parse_location(text)
    assert parsed is not None and parsed[0] == "listed"
    if countries is not None:
        assert set(parsed[1]) == countries


def test_combined_and_sales_region_names() -> None:
    both = parse_location("United States & EMEA")
    apj = parse_location("APJ")
    amer = parse_location("AMER")
    assert both is not None and {"US", "GB", "DE"} <= both[1] and "IN" not in both[1]
    assert apj is not None and "IN" in apj[1]
    assert amer is not None and "US" in amer[1] and "IN" not in amer[1]


@pytest.mark.parametrize(
    "text",
    [
        "Remote",
        "Hybrid",
        "Remote-Friendly",
        "",
        "Multiple Locations",
        # Placeholders in the live pool: they name no place and must stay unknown.
        "N/A",
        "LOCATION",
        "No Location",
        "In-person",
        # CIS has no agreed country list; left unknown rather than guessed.
        "CIS - Remote",
    ],
)
def test_locations_that_name_no_place_are_unparsed(text: str) -> None:
    assert parse_location(text) is None


# --- eligibility order -----------------------------------------------------------------


def test_structured_country_decides_onsite_and_hybrid_jobs() -> None:
    work = work_location(
        posting(
            source="lever",
            locations=["Remote - Anywhere"],
            workplace="hybrid",
            structured_countries=["IN"],
            structured_country_field="lever.country",
        ),
        "",
    )
    assert work == WorkLocation("listed", ("IN",), "lever.country")
    assert work.eligibility_for("IN") == "eligible"
    assert work.eligibility_for("US") == "ineligible"


def test_location_field_decides_remote_jobs_before_the_structured_country() -> None:
    work = work_location(
        posting(
            source="lever",
            locations=["Remote - Worldwide"],
            workplace="remote",
            structured_countries=["US"],
            structured_country_field="lever.country",
        ),
        "",
    )
    assert work.scope == "worldwide"
    assert work.source == "location:lever.location:worldwide"
    assert work.eligibility_for("IN") == "eligible"


def test_remote_job_with_no_place_in_its_location_uses_the_structured_country() -> None:
    work = work_location(
        posting(
            source="ashby",
            locations=["Remote"],
            workplace="remote",
            structured_countries=["US"],
            structured_country_field="ashby.address",
        ),
        "",
    )
    assert work == WorkLocation("listed", ("US",), "ashby.address")


def test_greenhouse_offices_are_a_fallback_after_the_location_field() -> None:
    work = work_location(
        posting(locations=["Remote-Friendly"], location_restriction="Bengaluru, Karnataka, India"),
        "",
    )
    assert work.countries == ("IN",)
    assert work.source == "location:greenhouse.offices:city"


def test_remotive_restriction_is_the_location_field() -> None:
    work = work_location(
        posting(
            source="remotive",
            locations=["LATAM, Europe, USA, Canada, APAC"],
            location_restriction="LATAM, Europe, USA, Canada, APAC",
        ),
        "",
    )
    assert work.source == "location:remotive.location:region"
    assert work.eligibility_for("IN") == "eligible"


@pytest.mark.parametrize(
    ("description", "scope", "countries", "rule"),
    [
        ("We hire from anywhere in the world.", "worldwide", (), "description:worldwide"),
        ("Candidates must be based in India.", "listed", ("IN",), "description:india"),
        (
            "You must be authorized to work in the United States.",
            "listed",
            ("US",),
            "description:us_only",
        ),
        ("US-based candidates only.", "listed", ("US",), "description:us_only"),
    ],
)
def test_description_rules(
    description: str, scope: str, countries: tuple[str, ...], rule: str
) -> None:
    assert from_description(description) == WorkLocation(scope, countries, rule)  # type: ignore[arg-type]


def test_description_is_only_consulted_when_fields_say_nothing() -> None:
    text = "Candidates must be based in India."
    assert work_location(posting(locations=["Remote"]), text).source == "description:india"
    assert work_location(posting(locations=["London"]), text).countries == ("GB",)


def test_no_evidence_is_unknown_never_eligible() -> None:
    work = work_location(posting(locations=["Remote"]), "A great team.")
    assert work == UNKNOWN
    assert work.eligibility_for("IN") == "unknown"


# --- skills --------------------------------------------------------------------------


def test_skills_use_canonical_names_and_aliases() -> None:
    text = "We use Postgres, k8s, Golang and React.js. Experience with GenAI and RAG is a plus."
    skills = extract_skills(text)
    for expected in ("PostgreSQL", "Kubernetes", "Go", "React", "LLMs", "RAG"):
        assert expected in skills


@pytest.mark.parametrize(
    ("text", "absent"),
    [
        ("Please send your CV and cover letter.", "Computer vision"),
        ("Go above and beyond for customers.", "Go"),
        ("We react quickly to feedback.", "React"),
        ("Series C funded company.", "C"),
        ("The rest of the team is in Berlin.", "REST APIs"),
        ("Enjoy the spring weather.", "Spring Boot"),
        ("Join GitLab and help us build.", "Git"),
    ],
)
def test_ambiguous_words_do_not_become_skills(text: str, absent: str) -> None:
    assert absent not in extract_skills(text)


@pytest.mark.parametrize(
    ("text", "present"),
    [
        ("Python, Go, Rust", "Go"),
        ("Languages: C/C++", "C++"),
        ("Skills: Python, R, SQL", "R"),
        ("C# and .NET Core", ".NET"),
        ("C# and .NET Core", "C#"),
        ("Node.js services", "Node.js"),
        ("scikit learn and PyTorch", "scikit-learn"),
    ],
)
def test_short_and_symbol_names_match_in_context(text: str, present: str) -> None:
    assert present in extract_skills(text)


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("postgres", "PostgreSQL"),
        ("Postgres", "PostgreSQL"),
        ("k8s", "Kubernetes"),
        ("react js", "React"),
        ("PostgreSQL", "PostgreSQL"),
        ("cobol", None),
    ],
)
def test_canonical_skill(alias: str, canonical: str | None) -> None:
    assert canonical_skill(alias) == canonical


# --- seniority and employment --------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Software Engineer", "mid"),
        ("Senior Software Engineer", "senior"),
        ("Sr. Backend Engineer", "senior"),
        ("Staff Engineer, Infrastructure", "staff"),
        ("Principal ML Engineer", "principal"),
        ("Engineering Manager, Payments", "manager"),
        ("Product Manager", "mid"),
        ("Senior Product Manager", "senior"),
        ("Director of Engineering", "director"),
        ("Head of Data", "director"),
        ("VP, Engineering", "executive"),
        ("Software Engineering Intern", "intern"),
        ("Junior Data Analyst", "junior"),
        ("New Grad Software Engineer", "junior"),
        ("SDE 1", "junior"),
        ("SDE-2", "mid"),
        ("Software Engineer II", "mid"),
        ("Software Engineer III", "senior"),
        ("Tech Lead, Platform", "lead"),
    ],
)
def test_seniority_from_title(title: str, level: str) -> None:
    assert seniority_from_title(title) == level


@pytest.mark.parametrize(
    ("source_value", "title", "expected"),
    [
        ("FullTime", "Engineer", "full_time"),
        ("full time", "Engineer", "full_time"),
        ("Contract", "Engineer", "contract"),
        ("freelance", "Writer", "contract"),
        ("part_time", "Support", "part_time"),
        ("Intern", "Engineer", "internship"),
        (None, "Summer Internship 2027", "internship"),
        (None, "Internal Tools Engineer", "full_time"),
        (None, "Engineer", "full_time"),
        # "Consultant" in a title is a role; as the source's own value it means contractor.
        (None, "Solutions Consultant, SMB (London)", "full_time"),
        ("Consultant", "Engineer", "contract"),
        (None, "Data Engineer (Contract)", "contract"),
        # A role about contracts is not a contract job (tag sheet 2026-11-25).
        (None, "Senior Contracts Manager", "full_time"),
        (None, "Contract Manager", "full_time"),
        (None, "Contracting Officer", "full_time"),
        (None, "Python Developer - Contractor", "contract"),
        (None, "Sanctions Investigator (1 year contractor)", "contract"),
        (None, "Contractual Data Entry Operator", "contract"),
    ],
)
def test_employment_type(source_value: str | None, title: str, expected: str) -> None:
    assert employment_type(source_value, title) == expected


# --- salary --------------------------------------------------------------------------


def test_fx_table_is_dated_and_converts_through_eur() -> None:
    date, usd_per_unit = fx_table()
    assert date == "2026-11-16"
    assert usd_per_unit["USD"] == 1.0
    assert usd_per_unit["INR"] == pytest.approx(1.1014 / 103.4520)
    assert to_annual_usd(2_000_000, "INR", "year") == round(2_000_000 * 1.1014 / 103.4520)
    assert to_annual_usd(50, "USD", "hour") == 104_000
    assert to_annual_usd(5_000, "EUR", "month") == round(60_000 * 1.1014)
    assert to_annual_usd(1, "XYZ", "year") is None
    assert to_annual_usd(None, "USD", "year") is None


def test_structured_salary_keeps_original_and_adds_usd() -> None:
    salary = from_structured(RawSalary(285000, 207000, "USD", "year"), "ashby.salary")
    assert salary == Salary(207000, 285000, "USD", "year", 207000, 285000, "ashby.salary")


@pytest.mark.parametrize(
    ("text", "low", "high", "currency", "interval"),
    [
        ("$170k - $200k", 170_000, 200_000, "USD", "year"),
        ("$35,3k- $52k", 35_300, 52_000, "USD", "year"),
        ("$14 - $20/hour", 14, 20, "USD", "hour"),
        ("$50-$75 /hour", 50, 75, "USD", "hour"),
        ("€60,000–€75,000", 60_000, 75_000, "EUR", "year"),
        ("£45,000 to £55,000 per year", 45_000, 55_000, "GBP", "year"),
        ("12-18 LPA", 1_200_000, 1_800_000, "INR", "year"),
        ("₹20,00,000 - ₹30,00,000", 2_000_000, 3_000_000, "INR", "year"),  # Indian grouping
        ("The base salary range is $150,000—$200,000 USD.", 150_000, 200_000, "USD", "year"),
    ],
)
def test_text_salary_parsing(
    text: str, low: float | None, high: float | None, currency: str | None, interval: str | None
) -> None:
    salary = from_text(text, "test")
    if low is None:
        assert salary is None or salary.currency == "INR"
        return
    assert salary is not None
    assert (salary.min, salary.max, salary.currency, salary.interval) == (
        low,
        high,
        currency,
        interval,
    )


@pytest.mark.parametrize(
    "text",
    [
        "$14/hour",
        "70K-80K",
        "$1000 per task",
        "OTE",
        "2-5 years of experience",
        "",
        None,
        "$50 - $100",
    ],
)
def test_ambiguous_salary_text_is_left_empty(text: str | None) -> None:
    assert from_text(text, "test") is None


# --- text ----------------------------------------------------------------------------


def test_html_to_text_decodes_greenhouse_double_encoding_and_drops_markup() -> None:
    raw = (
        "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;We build &amp;amp; ship.&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"
    )
    assert html_to_text(raw) == "About\n\nWe build & ship.\n\n- Python"


def test_html_to_text_removes_scripts_and_styles() -> None:
    raw = "<p>Hello</p><script>alert('x')</script><style>p{}</style><img src=x onerror=y>World"
    text = html_to_text(raw)
    assert "alert" not in text and "p{}" not in text and "onerror" not in text
    assert "Hello" in text and "World" in text


def test_normalised_keys() -> None:
    assert normalise_title("Senior Software Engineer (Remote)") == "senior software engineer"
    assert normalise_title("Backend Engineer - Hybrid") == "backend engineer"
    assert normalise_key("Bengaluru,  Karnataka – India") == "bengaluru karnataka india"
    assert normalise_key("Zürich") == "zurich"


def test_content_hash_changes_with_location_and_salary() -> None:
    base = content_hash("Engineer", "Build things.", "Mumbai", None)
    assert base == content_hash("Engineer", "Build   things.", "Mumbai", None)
    assert base != content_hash("Engineer", "Build things.", "Pune", None)
    salary = Salary(1, 2, "USD", "year", 1, 2, "x")
    assert base != content_hash("Engineer", "Build things.", "Mumbai", salary)


def test_normalise_end_to_end() -> None:
    job = normalise(
        posting(
            source="ashby",
            title="Senior Backend Engineer (Remote)",
            description_html="<p>Python, FastAPI and Postgres. Salary $150k - $180k.</p>",
            locations=["Remote - India"],
            workplace="remote",
            employment_type="FullTime",
        )
    )
    assert job.title_norm == "senior backend engineer"
    assert job.seniority == "senior"
    assert job.remote_policy == "remote"
    assert job.work.eligibility_for("IN") == "eligible"
    assert {"Python", "FastAPI", "PostgreSQL"} <= set(job.skills)
    assert job.salary is not None and job.salary.source == "description"
    assert job.salary.min_usd == 150_000


def test_workplace_from_location_text_when_the_source_has_no_field() -> None:
    assert normalise(posting(locations=["Remote - US"])).remote_policy == "remote"
    assert normalise(posting(locations=["London (Hybrid)"])).remote_policy == "hybrid"
    assert normalise(posting(locations=["London"])).remote_policy == "unknown"


# --- companies -----------------------------------------------------------------------


def test_companies_file_has_60_plus_tagged_unique_boards() -> None:
    curated = load_companies(discovered_path=None)
    assert len(curated) >= 60
    assert len({(c.ats, c.token) for c in curated}) == len(curated)
    assert all(c.industries for c in curated)
    assert all(c.discovered_via == "manual" for c in curated)


def test_discovered_boards_load_with_provenance_and_no_duplicates() -> None:
    every = load_companies()
    assert len({(c.ats, c.token) for c in every}) == len(every)
    discovered = [c for c in every if c.discovered_via != "manual"]
    assert discovered, "companies_discovered.yaml is expected in the repo"
    assert {c.discovered_via for c in discovered} <= {"yc-oss", "vc:elevation", "commoncrawl"}
    assert all(c.yc_batch for c in discovered if c.discovered_via == "yc-oss")
    assert all(
        c.investors == ("elevation",) for c in discovered if c.discovered_via == "vc:elevation"
    )


def test_company_slug_joins_name_variants() -> None:
    assert company_slug("Postman, Inc.") == company_slug("postman")
    assert company_slug("Sarvam AI") == "sarvam"
    assert company_slug("Coalition Technologies ") == "coalition"
    assert company_slug("AI") == "ai"


# --- gazetteer -----------------------------------------------------------------------


def test_every_gazetteer_code_is_a_two_letter_string() -> None:
    """Guards the YAML "Norway problem": an unquoted NO loads as the boolean false."""
    g = gazetteer()
    codes = set(g.codes) | set(g.countries.values()) | set(g.cities.values())
    codes |= {code for region in g.regions.values() for code in region}
    assert all(isinstance(c, str) and len(c) == 2 and c.isupper() for c in codes), codes
    assert "NO" in g.codes
    assert parse_location("Oslo, Norway") == ("listed", frozenset({"NO"}), "city")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("India", "IN"),
        ("United States", "US"),
        ("in", "IN"),
        ("United Kingdom", "GB"),
        ("Norway", "NO"),
        ("", None),
        ("Atlantis", None),
    ],
)
def test_country_code(name: str, code: str | None) -> None:
    assert country_code(name) == code
