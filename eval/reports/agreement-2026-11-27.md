# Agreement between the LLM judges: eval-2026-11-25

LLM-judged; no human labels.

### Blind pairs (120 pairs; graded {'gemini': 120, 'groq': 120, 'cowork': 120})

n is the number of pairs both judges graded.

| Judges | n | weighted kappa [95% CI] | exact | within one | mean a - b |
|---|---:|---|---:|---:|---:|
| gemini vs groq | 120 | 0.697 [0.585, 0.788] | 67.5% | 97.5% | -0.22 |
| gemini vs cowork | 120 | 0.658 [0.550, 0.746] | 65.0% | 99.2% | -0.04 |
| groq vs cowork | 120 | 0.677 [0.559, 0.769] | 63.3% | 97.5% | +0.17 |

#### gemini vs groq

Confusion (rows gemini, columns groq):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 5 | 0 | 2 | 0 |
| **1** | 3 | 36 | 12 | 1 |
| **2** | 0 | 5 | 31 | 16 |
| **3** | 0 | 0 | 0 | 9 |

Most common disagreements (gemini/groq): 2/3 x16, 1/2 x12, 2/1 x5, 1/0 x3, 0/2 x2.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 19 (49%); gemini higher 3, groq higher 16
  - `p21:5a41870f-b504-401b-8490-055ce068f8c7`: gemini 1, groq 3; gemini (lower): "The role is globally remote and matches the candidate's technical stack (Kubernetes, SRE/Platform), but the stated salary is an absurdly low USD 150 per month, which effectively rules it out."
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, groq 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, groq 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
- **seniority**: 24 (62%); gemini higher 4, groq higher 20
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, groq 2; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p01:02be8406-2647-40ab-baea-80a12d49e96b`: gemini 1, groq 2; gemini (lower): "The role requires being the first data scientist to build and own recommendation features from the ground up, which is too senior for a final-year student looking for junior or internship positions."
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, groq 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
- **location**: 19 (49%); gemini higher 4, groq higher 15
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, groq 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, groq 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
  - `p05:ffbd5224-c266-4d37-bda4-5e5e18da0ee4`: gemini 2, groq 3; gemini (lower): "The role matches the candidate's field, experience level (2+ years), location eligibility (Remote in India), and required skills. However, no salary is stated, capping the grade at 2."
- **gigs**: 5 (13%); gemini higher 0, groq higher 5
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, groq 2; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p19:82c9cbe4-cc26-4720-aa48-cd62e189aa6c`: gemini 0, groq 2; gemini (lower): "This is a freelance AI-training gig rather than a core engineering role on search and ranking. It involves creating training tasks for AI models rather than building production ranking systems."
  - `p06:da0d9dec-faef-4d80-b804-bbca1d13a644`: gemini 2, groq 3; gemini (lower): "The role matches the candidate's field, seniority, and location eligibility (IN), but the employment type is 'contract' (freelance/gig dealbreaker concern) and it lacks salary information."
- **none of these**: 3 (8%); gemini higher 1, groq higher 2
  - `p04:e22d1c40-07a7-4355-8517-58a170593053`: gemini 1, groq 2; gemini (lower): "The role is an internship in India, but it focuses on basic data scraping and directory building rather than the candidate's core background in statistics, SQL, and analytics."
  - `p16:7d8137c9-231f-4c77-b463-79a5bbc2d7c7`: gemini 2, groq 1; groq (lower): "Field matches (GenAI/LLM), but requires 3 years experience vs candidate’s 1.5 years and workplace is unknown, while candidate needs remote work."
  - `p24:7d464f44-e976-4552-8587-e43a1c71b613`: gemini 1, groq 2; gemini (lower): "The role is DevSecOps rather than MLOps, though it is fully remote worldwide. The candidate's primary focus is machine learning operations and infrastructure."
- **all disagreements**: 39 (100%); gemini higher 8, groq higher 31

#### gemini vs cowork

Confusion (rows gemini, columns cowork):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 2 | 5 | 0 | 0 |
| **1** | 3 | 39 | 9 | 1 |
| **2** | 0 | 13 | 31 | 8 |
| **3** | 0 | 0 | 3 | 6 |

Most common disagreements (gemini/cowork): 2/1 x13, 1/2 x9, 2/3 x8, 0/1 x5, 1/0 x3.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 9 (21%); gemini higher 0, cowork higher 9
  - `p21:5a41870f-b504-401b-8490-055ce068f8c7`: gemini 1, cowork 3; gemini (lower): "The role is globally remote and matches the candidate's technical stack (Kubernetes, SRE/Platform), but the stated salary is an absurdly low USD 150 per month, which effectively rules it out."
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
- **seniority**: 20 (48%); gemini higher 5, cowork higher 15
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: gemini 1, cowork 2; gemini (lower): "The role asks for an experienced machine learning engineer, while the candidate is a fresh graduate looking for a junior or intern position, representing a clear level mismatch."
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
- **location**: 10 (24%); gemini higher 1, cowork higher 9
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, cowork 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
  - `p05:b4528df2-efcc-4a70-be35-8dcc3551bc97`: gemini 1, cowork 2; gemini (lower): "The role requires 4-7 years of experience, making it too senior for this candidate with 2.5 years of experience, despite matching the tech stack and location."
- **gigs**: 6 (14%); gemini higher 2, cowork higher 4
  - `p02:95bd2f2d-3374-4397-a575-47f28c1160f8`: gemini 0, cowork 1; gemini (lower): "This is a freelance AI QA and rating gig focused on prompt evaluation rather than engineering or building ML systems, making it an irrelevant match for an ML engineer."
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, cowork 1; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p11:4c8dc726-f05a-46d6-a574-4d1586c04e73`: gemini 2, cowork 1; cowork (lower): "5+ yrs; AI harness experience required"
- **none of these**: 13 (31%); gemini higher 12, cowork higher 1
  - `p04:2064fc6a-3a2a-4a8f-b1ff-055adcc1303c`: gemini 2, cowork 1; cowork (lower): "2–4+ yrs required"
  - `p04:2902d7cb-1f69-421e-b8d7-4a4735a012cf`: gemini 2, cowork 1; cowork (lower): "Needs 3–6 yrs and Supply Chain Guru"
  - `p06:06848ac0-a745-4e3e-90ec-c24f8621d6df`: gemini 3, cowork 2; cowork (lower): "Fits, but posted 2021"
- **all disagreements**: 42 (100%); gemini higher 19, cowork higher 23

#### groq vs cowork

Confusion (rows groq, columns cowork):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 3 | 5 | 0 | 0 |
| **1** | 2 | 32 | 7 | 0 |
| **2** | 0 | 17 | 27 | 1 |
| **3** | 0 | 3 | 9 | 14 |

Most common disagreements (groq/cowork): 2/1 x17, 3/2 x9, 1/2 x7, 0/1 x5, 3/1 x3.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 2 (5%); groq higher 0, cowork higher 2
  - `p09:d3dcaa6b-d85b-4e69-8ce2-4e975a0e0fd3`: groq 1, cowork 2; groq (lower): "Job matches Java backend field and is remote in India, but requires 6‑12 years (candidate has 5) and does not state salary, a declared dealbreaker."
  - `p20:7377a6a8-fd1f-4bcf-bc3b-d72c8dc227e6`: groq 1, cowork 2; groq (lower): "The role is a Data Engineer (more engineering‑focused than the candidate’s analyst background) and the posting omits salary, so the $80k dealbreaker can’t be verified."
- **seniority**: 14 (32%); groq higher 5, cowork higher 9
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: groq 1, cowork 2; groq (lower): "The role is a full-time Machine Learning Engineer requiring experience, while the candidate is a fresh graduate with no industry experience; seniority mismatch outweighs eligibility and field match."
  - `p02:95bd2f2d-3374-4397-a575-47f28c1160f8`: groq 0, cowork 1; groq (lower): "The posting is a freelance LLM evaluation/AI QA trainer gig, not an engineering role; the candidate wants a junior/mid ML engineer position building models, so the job is irrelevant."
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: groq 2, cowork 1; cowork (lower): "Junior DE, office-only"
- **location**: 4 (9%); groq higher 0, cowork higher 4
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: groq 1, cowork 2; groq (lower): "The role is a full-time Machine Learning Engineer requiring experience, while the candidate is a fresh graduate with no industry experience; seniority mismatch outweighs eligibility and field match."
  - `p05:b4528df2-efcc-4a70-be35-8dcc3551bc97`: groq 1, cowork 2; groq (lower): "The role requires 4-7 years of data engineering experience, exceeding the candidate's 2.5 years and senior‑mid level; otherwise location and skills match."
  - `p22:ab42d5a2-30be-488e-9a43-c3a355a0d006`: groq 0, cowork 1; groq (lower): "The job is a remote‑only Developer Relations Engineer role, focused on advocacy and content, not a junior/mid full‑stack engineering position the candidate seeks, and it conflicts with the candidate's hybrid/onsite NL preference."
- **gigs**: 8 (18%); groq higher 6, cowork higher 2
  - `p11:4c8dc726-f05a-46d6-a574-4d1586c04e73`: groq 3, cowork 1; cowork (lower): "5+ yrs; AI harness experience required"
  - `p02:95bd2f2d-3374-4397-a575-47f28c1160f8`: groq 0, cowork 1; groq (lower): "The posting is a freelance LLM evaluation/AI QA trainer gig, not an engineering role; the candidate wants a junior/mid ML engineer position building models, so the job is irrelevant."
  - `p06:da0d9dec-faef-4d80-b804-bbca1d13a644`: groq 3, cowork 2; cowork (lower): "Strong fit but contract role"
- **none of these**: 21 (48%); groq higher 20, cowork higher 1
  - `p13:2064fc6a-3a2a-4a8f-b1ff-055adcc1303c`: groq 3, cowork 1; cowork (lower): "Same posting as #88"
  - `p25:a855eee4-f68d-4cd5-aaad-bff177c6e077`: groq 3, cowork 1; cowork (lower): "Needs open-source library maintainer experience"
  - `p01:02be8406-2647-40ab-baea-80a12d49e96b`: groq 2, cowork 1; cowork (lower): "Needs production recsys experience"
- **all disagreements**: 44 (100%); groq higher 31, cowork higher 13

3-judge majority (median of three): {'two_agree': 55, 'unanimous': 60, 'all_differ': 5, 'pairs': 120}

### Pooled pairs, Gemini vs Claude Cowork (500 pairs; graded {'gemini': 500, 'cowork': 121})

n is the number of pairs both judges graded.

| Judges | n | weighted kappa [95% CI] | exact | within one | mean a - b |
|---|---:|---|---:|---:|---:|
| gemini vs cowork | 121 | 0.659 [0.543, 0.751] | 65.3% | 99.2% | -0.04 |

#### gemini vs cowork

Confusion (rows gemini, columns cowork):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 2 | 5 | 0 | 0 |
| **1** | 3 | 39 | 9 | 1 |
| **2** | 0 | 13 | 32 | 8 |
| **3** | 0 | 0 | 3 | 6 |

Most common disagreements (gemini/cowork): 2/1 x13, 1/2 x9, 2/3 x8, 0/1 x5, 3/2 x3.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 9 (21%); gemini higher 0, cowork higher 9
  - `p21:5a41870f-b504-401b-8490-055ce068f8c7`: gemini 1, cowork 3; gemini (lower): "The role is globally remote and matches the candidate's technical stack (Kubernetes, SRE/Platform), but the stated salary is an absurdly low USD 150 per month, which effectively rules it out."
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
- **seniority**: 20 (48%); gemini higher 5, cowork higher 15
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: gemini 1, cowork 2; gemini (lower): "The role asks for an experienced machine learning engineer, while the candidate is a fresh graduate looking for a junior or intern position, representing a clear level mismatch."
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
- **location**: 10 (24%); gemini higher 1, cowork higher 9
  - `p02:39883b7c-418c-4406-8066-a87f2457389c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's field (NLP and LLMs) and is eligible for candidates in India with a remote setup. However, the exact seniority level and location within India are not explicitly detailed, and no salary is stated."
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, cowork 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
  - `p05:b4528df2-efcc-4a70-be35-8dcc3551bc97`: gemini 1, cowork 2; gemini (lower): "The role requires 4-7 years of experience, making it too senior for this candidate with 2.5 years of experience, despite matching the tech stack and location."
- **gigs**: 6 (14%); gemini higher 2, cowork higher 4
  - `p02:95bd2f2d-3374-4397-a575-47f28c1160f8`: gemini 0, cowork 1; gemini (lower): "This is a freelance AI QA and rating gig focused on prompt evaluation rather than engineering or building ML systems, making it an irrelevant match for an ML engineer."
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, cowork 1; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p11:4c8dc726-f05a-46d6-a574-4d1586c04e73`: gemini 2, cowork 1; cowork (lower): "5+ yrs; AI harness experience required"
- **none of these**: 13 (31%); gemini higher 12, cowork higher 1
  - `p04:2064fc6a-3a2a-4a8f-b1ff-055adcc1303c`: gemini 2, cowork 1; cowork (lower): "2–4+ yrs required"
  - `p04:2902d7cb-1f69-421e-b8d7-4a4735a012cf`: gemini 2, cowork 1; cowork (lower): "Needs 3–6 yrs and Supply Chain Guru"
  - `p06:06848ac0-a745-4e3e-90ec-c24f8621d6df`: gemini 3, cowork 2; cowork (lower): "Fits, but posted 2021"
- **all disagreements**: 42 (100%); gemini higher 19, cowork higher 23

