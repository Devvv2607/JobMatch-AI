# Embedding text v2: boilerplate stripping

Measured 2026-11-21 on the live pool (12,382 non-expired jobs) on an AMD Ryzen 7 7445HS
(6 cores / 12 threads), 15 GB RAM, Windows 11, Docker 29.9 with WSL2 capped at 6 GB.
Reproduce with `python -m scripts.embed_text_report` and
`python -m scripts.neighbour_check` (see each script's docstring).

## Re-embedding cost

`docker compose run --rm ingest python -m app.ingest.cli embed`: 12,382 jobs embedded in
3,031.5 s (50.5 min, 4.1 jobs/s). Peak memory: 531 MiB process peak RSS (getrusage);
479 MiB peak for the ingest container, 918 MiB for all containers and 2,764 MiB for the
Docker VM, from `docker stats` / vmmemWSL sampled every ~9 s.

## Tokens removed

Jobs: 12382 (non-expired, prepared). Token counts use the bge-small tokenizer,
untruncated, and include the [CLS]/[SEP] tokens.

| Measure | Before (v1) | After |
|---|---|---|
| Description tokens, mean | 1224 | 734 |
| Description tokens, median | 1170 | 690 |
| Card tokens, mean | 1248 | 764 |
| Cards longer than 512 tokens (truncated) | 12252 (99%) | 10066 (81%) |

Tokens removed per job: mean 491, median 452; jobs with nothing removed: 88; jobs left with an empty description: 1.

### Example 1: Sr. Forward Deployed Engineer (Databricks)

Description tokens: 1066 before, 718 after.

Removed (10 paragraphs):

- ~~The impact you will have:~~
- ~~What we look for:~~
- ~~About Databricks~~
- ~~Databricks is the Data and AI company. More than 20,000 organizations worldwide — including adidas, AT&T, Baye…~~
- ~~Benefits~~
- ~~At Databricks, we strive to provide comprehensive benefits and perks that meet the needs of all of our employe…~~
- ~~Our Commitment to Diversity and Inclusion~~
- ~~At Databricks, we are committed to fostering a diverse and inclusive culture where everyone can excel. We take…~~
- ~~Compliance~~
- ~~If access to export-controlled technology or source code is required for performance of job duties, it is with…~~

Kept (start): CSQ128R8 As a Forward Deployed Engineer (FDE) you will work with customers to build and productionize solutions to their data & AI challenges using the Databricks platform. You will own the architecture, lead design decisions, and implement end-to-end systems spanning data engineering, AI, and application development. We work cross-functionally to shape long-term strategic priorities and initiativ…

### Example 2: Software Engineer - Defense Applications (Palantir)

Description tokens: 1646 before, 857 after.

Removed (27 paragraphs):

- ~~A World-Changing Company~~
- ~~Palantir builds the world’s leading software for data-driven decisions and operations. By bringing the right d…~~
- ~~The Role~~
- ~~Core Responsibilities~~
- ~~What We Value~~
- ~~What We Require~~
- ~~Salary~~
- ~~Our benefits aim to promote health and wellbeing across all areas of Palantirians’ lives. We work to continuou…~~
- ~~Benefits~~
- ~~• Employees (and their eligible dependents) can enroll in medical, dental, and vision insurance as well as vol…~~
- ~~• Employees are automatically covered by Palantir’s basic life, AD&D and disability insurance~~
- ~~• Commuter benefits~~
- … 15 more

Kept (start): Palantir’s software forms the operating system for the militaries of the United States and her allies, driving outcomes and enhancing capabilities across the full spectrum of operations, intelligence, and support activities. Our defense applications are the tip of that spear, powerful tools used daily by thousands of soldiers, sailors, airmen, and marines to perform critical work at home and abroa…

### Example 3: Machine Learning Engineer, Link (Stripe)

Description tokens: 897 before, 744 after.

Removed (10 paragraphs):

- ~~Who we are~~
- ~~About Stripe~~
- ~~Stripe is a financial infrastructure platform for businesses. Millions of companies—from the world’s largest e…~~
- ~~About the team~~
- ~~What you’ll do~~
- ~~Responsibilities~~
- ~~Who you are~~
- ~~We’re looking for someone who meets the minimum requirements to be considered for the role. If you meet these …~~
- ~~Minimum requirements~~
- ~~Preferred qualifications~~

Kept (start): Link is a digital wallet designed for fast and secure online payments. It allows consumers to save and use their preferred payment methods across the Link network, helping them check out quickly and securely wherever Link is accepted. The Link Fraud and Auth team works to make Link the most trusted and highest-performing way to pay. We protect consumers and merchants from fraud, abuse, and financi…

### Example 4: Regulatory Attorney (Palantir)

Description tokens: 1183 before, 911 after.

Removed (9 paragraphs):

- ~~A World-Changing Company~~
- ~~Palantir builds the world’s leading software for data-driven decisions and operations. By bringing the right d…~~
- ~~The Role~~
- ~~Core Responsibilities~~
- ~~What We Value~~
- ~~What We Require~~
- ~~Life at Palantir~~
- ~~We want every Palantirian to achieve their best outcomes, that’s why we celebrate individuals’ strengths, skil…~~
- ~~Please note that you will never be asked to submit a payment or share financial information to participate in …~~

Kept (start): Palantir is seeking a Regulatory Counsel to join our Compliance function within the Legal Team. Our team’s mission is to proactively provide compliance advice to the business, in an effort to support Palantir’s responsible business growth. In this role, you’ll support teams across the global business as they navigate various regulatory and contractural requirements to ensure compliance with applic…

### Example 5: Forward Deployed Site Reliability Engineer - US Government (Palantir)

Description tokens: 1468 before, 679 after.

Removed (27 paragraphs):

- ~~A World-Changing Company~~
- ~~Palantir builds the world’s leading software for data-driven decisions and operations. By bringing the right d…~~
- ~~The Role~~
- ~~Core Responsibilities~~
- ~~What We Value~~
- ~~What We Require~~
- ~~Salary~~
- ~~Our benefits aim to promote health and wellbeing across all areas of Palantirians’ lives. We work to continuou…~~
- ~~Benefits~~
- ~~• Employees (and their eligible dependents) can enroll in medical, dental, and vision insurance as well as vol…~~
- ~~• Employees are automatically covered by Palantir’s basic life, AD&D and disability insurance~~
- ~~• Commuter benefits~~
- … 15 more

Kept (start): We’re looking for Forward Deployed Site Reliability Engineers who can help us build, operate, and maintain high-performance, scalable, and reliable services for our production infrastructure, primarily across on-prem environments for the US Government. Forward Deployed Site Reliability Engineers combine engineering experience and an innate drive to improve existing systems and processes, with the …


## Nearest neighbours before and after (sanity check, not an evaluation)

10 random active, non-duplicate jobs (seed 7). For each: its 5 nearest neighbours by
exact cosine among active, non-duplicate jobs, using the v1 vectors (snapshot taken before
re-embedding) and the v2 vectors. Both columns search the same set of jobs.

#### 1. Senior SRE, Managed Gateways (Kong)

| # | Before | After |
|---|---|---|
| 1 | Software Engineering Manager, Managed Gateways SREs (Kong) 0.944 | Software Engineering Manager, Managed Gateways SREs (Kong) 0.947 |
| 2 | Senior Software Engineer (Kong) 0.914 | Platform Engineering Manager (Kong) 0.915 |
| 3 | Software Engineer 2, Managed Gateways (Kong) 0.910 | Senior Software Engineer (Kong) 0.915 |
| 4 | Site Reliability Engineer 2 (Kong) 0.910 | Engineering Manager, Managed Gateways (Kong) 0.912 |
| 5 | Engineering Manager, Managed Gateways (Kong) 0.905 | Senior Software Engineer - Kubernetes (Kong) 0.905 |

#### 2. Product Management - UPI Product | Experience : 3-5 yrs (Paytm)

| # | Before | After |
|---|---|---|
| 1 | Product Management - UPI Product | Experience : 6-9 yrs (Paytm) 0.979 | Product Management - UPI Product | Experience : 3-5 yrs (Paytm) 0.960 |
| 2 | Product Management - UPI Product | Experience : 3-5 yrs (Paytm) 0.979 | Product Management - UPI Product | Experience : 6-9 yrs (Paytm) 0.956 |
| 3 | Product Management - App Product (Paytm) 0.970 | Product Management - App Product (Paytm) 0.945 |
| 4 | Product Management - Lending Product | Experience : 4 -8 yrs (Paytm) 0.950 | Product Management - Product Manager II - Travel (Paytm) 0.930 |
| 5 | Product Management - Data Product | Experience : 5-8 yrs (Paytm) 0.948 | Product Management - AI Payments (Paytm) 0.929 |

#### 3. Manager, Commercial Operations (ClickHouse)

| # | Before | After |
|---|---|---|
| 1 | Principal Product Manager, Billing & Marketplaces (ClickHouse) 0.884 | Principal Product Manager, Billing & Marketplaces (ClickHouse) 0.901 |
| 2 | Principal Product Manager, Billing & Marketplaces (ClickHouse) 0.884 | Principal Product Manager, Billing & Marketplaces (ClickHouse) 0.895 |
| 3 | Senior Manager, Order-to-Cash (ClickHouse) 0.880 | Monetization Operations & Systems Lead (LangChain) 0.890 |
| 4 | Senior Product Manager, Billing & Marketplaces (ClickHouse) 0.880 | Senior Manager, Order-to-Cash (ClickHouse) 0.889 |
| 5 | Senior Product Manager, Billing & Marketplaces (ClickHouse) 0.880 | Monetization Operations & Systems Lead (LangChain) 0.889 |

#### 4. Stock Margin Operations, Senior/Analyst (Binance)

| # | Before | After |
|---|---|---|
| 1 | Senior Product Manager, Core Trading (Binance) 0.936 | Operations Leader - Binance Wallet (Binance) 0.877 |
| 2 | Spot Operations Specialist (Binance) 0.933 | Operations Specialist - Gulf Binance (Binance) 0.874 |
| 3 | Senior Algorithmic Trader / Liquidity Researcher (Binance) 0.928 | Risk Operations Agent (AMER, US Timezone) - 8-months Contract (Binance) 0.874 |
| 4 | Senior Growth Manager - CIS (Binance) 0.928 | Financial Data Engineer, Stock & AI Data(APAC - Remote) (Binance) 0.872 |
| 5 | Finance Analyst (12 months contract) (Binance) 0.928 | Binance Accelerator Program - VIP User Operations (Binance) 0.871 |

#### 5. Senior Machine Learning Engineer, 3D Data (Roblox)

| # | Before | After |
|---|---|---|
| 1 | Senior Software Engineer, Computer Graphics (Roblox) 0.948 | Senior Software Engineer, Computer Graphics (Roblox) 0.938 |
| 2 | [2027] Senior Machine Learning Engineer - PhD Early Career (Roblox) 0.942 | Senior Machine Learning Engineer (Cloudflare) 0.914 |
| 3 | Senior Software Engineer, Content Understanding (Roblox) 0.934 | Senior Software Engineer (Backend) - AI/ML Environments (Databricks) 0.906 |
| 4 | Senior Machine Learning Engineer, Behavioral Detection (Roblox) 0.934 | Staff Engineer, Machine Learning & Data Infrastructure (OKX) 0.902 |
| 5 | Senior Software Engineer, Data Engineering (Roblox) 0.932 | Senior Machine Learning Engineer, Public Sector (Scale AI) 0.901 |

#### 6. Executive Assistant, People (Figma)

| # | Before | After |
|---|---|---|
| 1 | Executive Assistant, Growth Marketing (Figma) 0.942 | Executive Assistant, CEO (Figma) 0.910 |
| 2 | Executive Assistant, CEO (Figma) 0.941 | People Partner (Figma) 0.899 |
| 3 | People Partner (Figma) 0.919 | Executive Assistant, Growth Marketing (Figma) 0.893 |
| 4 | Senior Account Executive, SMB (Figma) 0.910 | Account Executive, Strategic (Figma) 0.863 |
| 5 | Account Executive, Strategic (Figma) 0.909 | Account Executive, Enterprise (Figma) 0.861 |

#### 7. Database Support Engineer (EMEA) (Supabase)

| # | Before | After |
|---|---|---|
| 1 | Database Support Engineer (AMER) (Supabase) 0.975 | Database Support Engineer (APAC) (Supabase) 0.961 |
| 2 | Database Support Engineer (APAC) (Supabase) 0.974 | Database Support Engineer (AMER) (Supabase) 0.957 |
| 3 | Support Engineer (EMEA) (Supabase) 0.971 | Support Engineer (EMEA) (Supabase) 0.948 |
| 4 | Support Engineer (EMEA - Weekends) (Supabase) 0.968 | Support Engineer (EMEA - Weekends) (Supabase) 0.945 |
| 5 | Support Engineer (APAC) (Supabase) 0.955 | Database Support Engineer (Japanese Speaking) (Supabase) 0.916 |

#### 8. Engineering Manager - Experimentation (Spotify)

| # | Before | After |
|---|---|---|
| 1 | Engineering Manager - Experimentation (Spotify) 0.995 | Engineering Manager - Experimentation (Spotify) 0.990 |
| 2 | Senior Engineering Manager - Information Technology (Spotify) 0.906 | Senior Engineering Manager - Information Technology (Spotify) 0.906 |
| 3 | Engineering Manager - Data Platform (Spotify) 0.900 | Engineering Manager - Data Platform (Spotify) 0.903 |
| 4 | Senior Machine Learning Engineering Manager - Content Platform (Spotify) 0.885 | Senior Machine Learning Engineering Manager - Content Platform (Spotify) 0.885 |
| 5 | Machine Learning Engineering Manager II (Spotify) 0.884 | Principal Product Manager - Core Experience Platform (Spotify) 0.885 |

#### 9. Senior Counsel, Competition (OpenAI)

| # | Before | After |
|---|---|---|
| 1 | Senior Counsel, Litigation (Safety) (OpenAI) 0.942 | Senior Counsel, Litigation (Safety) (OpenAI) 0.934 |
| 2 | Senior Counsel, Commercial (Health and Life Sciences) (OpenAI) 0.937 | Senior Counsel, Commercial (Health and Life Sciences) (OpenAI) 0.928 |
| 3 | Senior Counsel, AI Product (Enterprise/API) (OpenAI) 0.930 | Senior Counsel, Commercial (Infrastructure) (OpenAI) 0.924 |
| 4 | Senior Counsel, Commercial (Infrastructure) (OpenAI) 0.928 | Senior Counsel, AI Product (Enterprise/API) (OpenAI) 0.923 |
| 5 | Senior Counsel, Trademark (OpenAI) 0.922 | Senior Counsel, Trademark (OpenAI) 0.916 |

#### 10. Workplace Services Manager (Roblox)

| # | Before | After |
|---|---|---|
| 1 | Receptionist (Roblox) 0.899 | Global Workplace Services Manager, Events & Experiences (Databricks) 0.837 |
| 2 | Executive Business Partner, Chief Business Officer (Roblox) 0.877 | Manager, Workplace (MongoDB) 0.837 |
| 3 | International Operations Manager (Roblox) 0.876 | Executive Business Partner, Chief Business Officer (Roblox) 0.835 |
| 4 | Engineering Manager, App Performance (Roblox) 0.874 | Workplace Operation Manager — New York City (OpenAI) 0.830 |
| 5 | Manager, Product Support Operations (Roblox) 0.872 | Senior Manager, Occupancy Planning & Workplace Strategy (OpenAI) 0.816 |

Neighbours at the same company as the query job: before 50/50, after 40/50

## Memory of a full ingest run, after the store-step and embed-thread fixes

| Run (2026-11-21) | Store step | Whole run |
|---|---|---|
| Before the single-thread fix, 545 jobs embedded | 441–466 MiB container; 534 MiB process RSS after the last store | 1,001 MiB process RSS; 902 MiB container; 2,543 MiB Docker VM |
| After it, 551 jobs embedded | 544 MiB process RSS after the last store | 834 MiB process RSS (container and VM not sampled: the sampler was stopped by host memory pressure) |
| For comparison, 2026-11-20 (full rows loaded in the store step), 1,247 jobs embedded | ~809 MiB container | 1,146 MiB container; 2,682 MiB Docker VM |
