"""Engagement and poster tags (app/ingest/tags.py, rules in data/tags.yaml), and the two
dealbreakers built on them. Each rule has a positive case; false positives are listed
explicitly."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.tags import engagement_type, poster_type
from app.retrieval.filters import allowed_ids
from app.retrieval.rules import ExcludeFreelanceGigs, ExcludeStaffingAgencies
from tests.search_helpers import add_company, add_job


@pytest.mark.parametrize(
    ("employment", "title", "description", "expected"),
    [
        # Structured type kept when nothing says gig.
        ("full_time", "Backend Engineer", "Python. Salary $140k.", "full_time"),
        ("part_time", "Support Agent", "20 hours a week.", "part_time"),
        ("contract", "Data Engineer (6 months)", "Contract role.", "contract"),
        ("internship", "Data Science Intern", "Paid internship.", "internship"),
        # Gig titles.
        (
            "contract",
            "Detective & Police Officers - Freelance AI Trainer Project",
            "",
            "freelance_gig",
        ),
        ("full_time", "Afrikaans Voice Acting Specialist - AI Trainer", "", "freelance_gig"),
        ("full_time", "Expert Rater", "", "freelance_gig"),
        ("contract", "Search Quality Raters (Hindi)", "", "freelance_gig"),
        ("full_time", "Medical Data Annotator", "", "freelance_gig"),
        ("full_time", "Freelance English into Danish Translator", "", "freelance_gig"),
        # Pay phrases count for contract / part-time jobs only.
        ("contract", "Hindi Culture Expert", "Project-based work, paid per task.", "freelance_gig"),
        ("part_time", "Math Tutor", "Earn $30 /hr, flexible.", "freelance_gig"),
        (
            "full_time",
            "Warehouse Associate",
            "Starting at $21 per hour plus benefits.",
            "full_time",
        ),
        # An internship stays an internship.
        ("internship", "AI Training Intern", "", "internship"),
        # False positives the patterns must not hit.
        ("full_time", "Underwriter", "", "full_time"),
        ("full_time", "Integrator Engineer", "", "full_time"),
        ("full_time", "ML Engineer, Data Labelling Platform", "", "full_time"),
        ("full_time", "Annotation Tools Engineer", "", "full_time"),
        ("contract", "Data Labeller (Telugu)", "", "freelance_gig"),
    ],
)
def test_engagement_type(employment: str, title: str, description: str, expected: str) -> None:
    assert engagement_type(employment, title, description, "Acme") == expected


@pytest.mark.parametrize(
    ("employment", "title", "description", "company", "expected"),
    [
        # Owner review 2026-11-25: AI-training work is gig work even when called contract.
        (
            "contract",
            "Humanitarian Aid Representative",
            "micro1 is engaging aid workers to help train AI.",
            "micro1",
            "freelance_gig",
        ),
        ("contract", "Video Editor", "Edit videos.", "micro1", "freelance_gig"),
        (
            "full_time",
            "Aerospace Engineer - Fully Remote | Upto $85/hr",
            "",
            "mercor",
            "freelance_gig",
        ),
        (
            "contract",
            "Videographers Needed to Help Train AI Models",
            "",
            "Lifted (an Upwork Company)",
            "freelance_gig",
        ),
        (
            "contract",
            "Shape the Future of AI - Urdu Talent Hub",
            "",
            "Welo Global",
            "freelance_gig",
        ),
        ("contract", "Indian Voice Recorders", "", "Your Personal AI", "freelance_gig"),
        (
            "contract",
            "Spanish Writer",
            "Flexible remote work helping train AI models.",
            "Acme",
            "freelance_gig",
        ),
        # Commission-only partnerships.
        (
            "contract",
            "Channel Partner - School Programs (Pan-India, Commission-Based)",
            "",
            "IMAV Learning Academy",
            "freelance_gig",
        ),
        (
            "full_time",
            "Sales Associate",
            "This is a commission-only role.",
            "Acme",
            "freelance_gig",
        ),
        # A staffing agency's hourly subcontract stays a contract.
        (
            "contract",
            "Senior ServiceNow Consultant_India",
            "6-9 month subcontract at $40/hour.",
            "AIDA Recruitment",
            "contract",
        ),
        # False positives: vendors' own staff, ML engineering, ordinary commission.
        ("full_time", "Software Engineer - Backend", "Build our platform.", "micro1", "full_time"),
        ("full_time", "Applied AI Research Engineer", "", "Appen Butler Hill Inc", "full_time"),
        (
            "full_time",
            "ML Engineer",
            "You will train AI models on large GPU clusters.",
            "Acme",
            "full_time",
        ),
        (
            "contract",
            "ML Infrastructure Engineer (6 months)",
            "Scale our AI training infrastructure.",
            "Acme",
            "contract",
        ),
        ("full_time", "Account Executive", "Base salary plus commission.", "Acme", "full_time"),
        ("contract", "Data Engineer", "Hourly rate $60.", "Acme", "freelance_gig"),
        (
            "contract",
            "Linux Infrastructure Engineer",
            "Experience supporting GPU clusters, AI training environments.",
            "Acme",
            "contract",
        ),
        ("contract", "DevOps", "Collaborate with researchers and annotators.", "Acme", "contract"),
        # Tag sheet 2026-11-25 (after the first retag).
        ("full_time", "Gujarati AI Translation Trainer", "", "Welocalize", "freelance_gig"),
        ("full_time", "At-Home Video Recorder (LATAM)", "", "micro1", "freelance_gig"),
        (
            "contract",
            "AI Red-Teaming Research Task Author (USD 60/task)",
            "",
            "RustLabs",
            "freelance_gig",
        ),
        ("full_time", "AI Model Training Engineer", "", "Acme", "full_time"),
        ("full_time", "Network Video Recorder Firmware Engineer", "", "Acme", "full_time"),
    ],
)
def test_engagement_type_with_company(
    employment: str, title: str, description: str, company: str, expected: str
) -> None:
    assert engagement_type(employment, title, description, company) == expected


@pytest.mark.parametrize(
    ("company", "description", "expected"),
    [
        # Names.
        ("Jobskey Consultancy", "Java developer.", "staffing_agency"),
        ("Neo Credence Consultancy", "", "staffing_agency"),
        ("Acme Staffing Solutions", "", "staffing_agency"),
        ("Bright Recruitment Ltd", "", "staffing_agency"),
        ("Talent Placement Services", "", "staffing_agency"),
        ("YD Talent Solutions", "", "staffing_agency"),
        # Descriptions.
        (
            "PradeepIT Consulting Services",
            "Hiring on behalf of our client, a leading IT services company.",
            "staffing_agency",
        ),
        ("Acme", "Our client is a Series B fintech in Bengaluru.", "staffing_agency"),
        ("Acme", "We are hiring for one of our esteemed clients.", "staffing_agency"),
        ("Acme", "We are a leading IT staffing agency.", "staffing_agency"),
        # False positives: consulting firms and employers mentioning clients or agencies.
        ("Boston Consulting Group", "Help our clients transform.", "employer"),
        ("Deloitte Consulting", "You will work with our clients across sectors.", "employer"),
        ("Acme", "Join our Client Success team.", "employer"),
        ("Acme", "Our client success managers own renewals.", "employer"),
        ("Acme", "We build software for our clients in retail.", "employer"),
        (
            "Acme",
            "No recruitment agencies, please. We do not accept CVs from agencies.",
            "employer",
        ),
        ("Acme", "Agencies need not apply.", "employer"),
        # Spot check 2026-11-25: employers describing their own customers.
        ("PharmaForceIQ", "Going above and beyond on behalf of our clients every day.", "employer"),
        ("Comscore", "We simplify the complex on behalf of our clients & partners.", "employer"),
        (
            "ZipTalents",
            "On behalf of our Scandinavian client, we are looking for SDRs.",
            "staffing_agency",
        ),
        (
            "TechBiz Global",
            "Seeking an engineer to join one of our clients' teams.",
            "staffing_agency",
        ),
        # Owner review 2026-11-25: recall gaps.
        (
            "TechBiz Global",
            "We provide recruitment services to tech firms. Join one of our client's teams.",
            "staffing_agency",
        ),
        ("TechBiz Global", "We provide recruitment services to tech firms.", "staffing_agency"),
        ("Staff Outsource Solutions", "", "staffing_agency"),
        (
            "Acme",
            "We are looking for a lead for our client, a fintech in Dubai.",
            "staffing_agency",
        ),
        ("Acme", "We are seeking a QA Analyst for a consulting client.", "staffing_agency"),
        ("Acme", "Your CV may be shared with our client(s).", "staffing_agency"),
        ("Acme", "Hiring for our client in Pune.", "staffing_agency"),
        # ... and the false positives they must not add.
        ("Acme", "Our client-facing teams work across regions.", "employer"),
        ("Acme", "Our client services team supports renewals.", "employer"),
        ("Acme", "We deliver great outcomes for our clients.", "employer"),
        ("Acme", "Build tools for a client-first company.", "employer"),
        # Seen on the pool 2026-11-25 when the singular phrases were added.
        ("Acme", "Guide users as they navigate our client's platform.", "employer"),
        ("Acme", "Deliver digital marketing for a diverse client base.", "employer"),
        ("Acme", "We are looking for an exceptional Client Partner to join us.", "employer"),
        ("Acme", "Deliver the best expert profiles to our Client Contributors.", "employer"),
        ("Acme", "Optimise order-to-cash processes for our retail client.", "employer"),
        # Owner review 2026-11-25: an employer serving its customer.
        ("BCD Travel", "You will work directly with our client to tell a story.", "employer"),
        ("Acme", "Working closely with our client on reporting.", "employer"),
        ("Recruitee", "Recruitee builds hiring software.", "employer"),
        ("Recruit Holdings", "", "employer"),
        ("Acme", "Our recruiting team will contact you.", "employer"),
    ],
)
def test_poster_type(company: str, description: str, expected: str) -> None:
    assert poster_type(company, description) == expected


async def test_gig_and_agency_dealbreakers_exclude_only_their_tag(session: AsyncSession) -> None:
    company = await add_company(session, "Acme")
    regular = await add_job(session, company, "Backend Engineer")
    gig = await add_job(session, company, "AI Trainer", engagement_type="freelance_gig")
    agency = await add_job(session, company, "Java Developer", poster_type="staffing_agency")
    await session.commit()

    no_gigs = set(await allowed_ids(session, [ExcludeFreelanceGigs()]))
    no_agencies = set(await allowed_ids(session, [ExcludeStaffingAgencies()]))
    assert no_gigs == {regular.id, agency.id}
    assert no_agencies == {regular.id, gig.id}
    both = set(await allowed_ids(session, [ExcludeFreelanceGigs(), ExcludeStaffingAgencies()]))
    assert both == {regular.id}
