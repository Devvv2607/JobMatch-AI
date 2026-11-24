# Near-duplicate review sample

Finder: app.ingest.dedup.find_text_duplicates, Jaccard threshold 0.9, cross-source containment 0.6. Pairs found: 1406 (104 cross_source, 1302 near_duplicate_text); buckets skipped (over the size cap): 0. Sample: 50 pairs, seed 7.

**Review (2026-11-24): 48 same, 1 different (#27), 1 unsure (#21). Precision 48/49 = 98.0%
of decided pairs; 48/50 = 96% if the unsure pair is counted as wrong.** Reviewed by Claude
(the assistant) reading each pair's titles, locations and differing words, not by the
owner; "same" means the same role and text, possibly in another city ("also posted in X").
The sample is dominated by a few companies posting one role in many US cities
(Databricks, Fivetran, Palantir, Harvey) and Swiggy's Account Manager across Indian cities.


| # | kind | score | company | title | A (kept) | B (duplicate) | words only in A | words only in B | verdict |
|---:|---|---:|---|---|---|---|---|---|---|
| 1 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: San Francisco, California | greenhouse: Raleigh, North Carolina | - | - | same |
| 2 | near_duplicate_text | 1.000 | Harvey | Legal Engineer (Law Firm, Litigation/Regulatory) | ashby: Chicago | ashby: Boston | - | - | same |
| 3 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: San Francisco, California | greenhouse: Washington, D.C. | - | - | same |
| 4 | cross_source | 1.000 | Particle41 | DevOps Engineer | himalayas:  | adzuna: India | abilities access address addressing administrator administrators ansible application applications architect assessments associate | - | same |
| 5 | cross_source | 0.773 | Canonical | Go (Golang) Software Engineer, Developer Tooling and Containers | greenhouse: Home Based - APAC | himalayas:  | agents aiming allowances an annual bachelor business coding committed companies competitive computer | ability academic across addition alternative anywhere apac be better can canonical carefully | same: two versions of the same Canonical posting (identical title, containment 0.773) |
| 6 | cross_source | 0.978 | Coinbase | Senior Engineering Manager | greenhouse: Remote - India | himalayas:  | also li may remote | accommodation accommodations are click coinbase.com compatible contact disability download email free here | same |
| 7 | near_duplicate_text | 1.000 | Swiggy | Account Manager | smartrecruiters: Bengaluru, KA, IN | smartrecruiters: Chennai, TN, IN | - | - | same |
| 8 | near_duplicate_text | 1.000 | Swiggy | Account Manager | smartrecruiters: Kurnool, AP, IN | smartrecruiters: Jaisalmer, RJ, IN | - | - | same |
| 9 | near_duplicate_text | 0.963 | Databricks | Staff Software Engineer - Backend | greenhouse: San Francisco, California | greenhouse: Bellevue, Washington | 150 192 260 | 182 247 400 940 | same: only location pay figures differ |
| 10 | near_duplicate_text | 0.997 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: Seattle, Washington | greenhouse: New York City, New York | - | sr | same |
| 11 | near_duplicate_text | 0.974 | MongoDB | Senior Solutions Architect (Pre-Sales) | greenhouse: Chicago | greenhouse: Atlanta; Charlotte; Miami; Orlando; Raleigh | 3273604958 chicago | 427022 atlanta charlotte durham miami orlando raleigh rdu | same |
| 12 | near_duplicate_text | 1.000 | Fivetran | Senior Internal Communications Manager | greenhouse: Remote, California, United States, AMER | greenhouse: Remote, Colorado, United States, AMER | - | - | same |
| 13 | near_duplicate_text | 1.000 | Kong | Staff Solutions Engineer | ashby: Texas, United States | ashby: New York, United States | - | - | same |
| 14 | cross_source | 1.000 | Twilio | Staff, Technical Account Manager | greenhouse: Remote - India | himalayas:  | - | about all apps ask banking businessesand cards care comfort communications conduct craft | same |
| 15 | cross_source | 0.983 | Coinbase | Staff Software Engineer, Security Platform | greenhouse: Remote - India | himalayas:  | also li may remote | accommodation accommodations click coinbase.com compatible contact disability download email free here himalayas | same |
| 16 | near_duplicate_text | 1.000 | Databricks | Solutions Architect - Games | greenhouse: West Coast - United States | greenhouse: Washington | - | - | same |
| 17 | near_duplicate_text | 1.000 | Palantir | Technical Writer | lever: New York, NY | lever: Washington, D.C. | - | - | same |
| 18 | near_duplicate_text | 1.000 | Harvey | Sales Development Representative | ashby: San Francisco | ashby: New York | - | - | same |
| 19 | near_duplicate_text | 1.000 | Swiggy | Account Manager | smartrecruiters: Warangal, TS, IN | smartrecruiters: Surat, GJ, IN | - | - | same |
| 20 | near_duplicate_text | 1.000 | Fivetran | Senior Partner Operations Manager | greenhouse: Remote, Illinois, United States, AMER | greenhouse: Remote, Georgia, United States, AMER | - | - | same |
| 21 | cross_source | 0.676 | AlphaSense | Content Analyst | greenhouse: Mumbai | himalayas:  | able additionally adjusting admin aggregation alerts augment available bachelor base basic because | 000 2011 2024 500 accelerate accountability acquisition address advances ai all alongside | unsure: same title and company; Himalayas-only words look like company boilerplate (2011, 500, acquisition), but a third of the Greenhouse text is missing from it |
| 22 | cross_source | 0.989 | Kong | Enterprise Account Executive | ashby: Bangalore, India | himalayas:  | li sp1 | 500 accelerate ai alike any api apis building cloud company connectivity enables | same |
| 23 | near_duplicate_text | 1.000 | Elastic | Strategic Account Executive - Financial Services | greenhouse: New York City, NY | greenhouse: Arizona, United States | - | - | same |
| 24 | near_duplicate_text | 0.977 | Palantir | Intellectual Property Counsel | lever: Washington, D.C. | lever: Denver, CO | - | accept application applications basis deadline ongoing | same: B adds an application-deadline sentence |
| 25 | near_duplicate_text | 0.947 | Fivetran | Lifecycle Marketing Manager | greenhouse: USA - Austin (dbt) | greenhouse: USA - New York (dbt) | 112 135 167.75 635.50 austin texas | 120 144 691 835 ny york | same: only location pay figures differ |
| 26 | near_duplicate_text | 1.000 | Fivetran | Senior Internal Communications Manager | greenhouse: Remote, California, United States, AMER | greenhouse: Remote, New York, United States, AMER | - | - | same |
| 27 | near_duplicate_text | 0.947 | Palantir | Deployment Strategist - US Government | lever: Honolulu, HI | lever: Laurel, MD | about analysis aviation leaders logistics material re readiness senior sustainment up | 75 executives location required suite varies | different: Honolulu text is about aviation/logistics readiness (sustainment, material); Laurel describes another mission; shared boilerplate only |
| 28 | near_duplicate_text | 1.000 | Fivetran | Senior Internal Communications Manager | greenhouse: Remote, New York, United States, AMER | greenhouse: Remote, Washington, United States, AMER | - | - | same |
| 29 | near_duplicate_text | 0.997 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: San Francisco, California | greenhouse: Seattle, Washington | sr | - | same |
| 30 | near_duplicate_text | 0.970 | Swiggy | Account Manager | smartrecruiters: Ranchi, JH, IN | smartrecruiters: Vijayawada, AP, IN | base days desired employees locations office respective their ways | - | same |
| 31 | cross_source | 1.000 | Clipbook | Media Intelligence Associate (Part-Time, Weekend Coverage) - India | ashby: India - Remote | himalayas:  | - | himalayas on originally posted | same |
| 32 | cross_source | 1.000 | Twilio | Principal Engineer (L5) | greenhouse: Remote - India | himalayas:  | - | himalayas originally posted | same |
| 33 | near_duplicate_text | 0.989 | Harvey | Staff Product Designer | ashby: San Francisco | ashby: New York | sb1 | jc1 | same |
| 34 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer (FDE) - Digital Native Business | greenhouse: San Francisco, California | greenhouse: West Coast - United States | - | - | same |
| 35 | near_duplicate_text | 1.000 | Swiggy | Account Manager | smartrecruiters: Vijayawada, AP, IN | smartrecruiters: Bareilly, UP, IN | - | - | same |
| 36 | near_duplicate_text | 1.000 | Fivetran | Senior Marketing Manager, Commercial | greenhouse: USA - Philadelphia (dbt) | greenhouse: USA - New York (dbt) | - | - | same |
| 37 | near_duplicate_text | 0.958 | Fivetran | Marketing Strategy Insights Lead | greenhouse: Denver, Colorado, United States, AMER | greenhouse: Oakland, California, United States, AMER | 182 228 260 608 denver hybrid jc1 li | 193 242 376 901 oakland | same: only location pay figures differ |
| 38 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer | greenhouse: Austin, Texas | greenhouse: Chicago, Illinois | - | - | same |
| 39 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: Boston, Massachusetts | greenhouse: Philadelphia, Pennsylvania | - | - | same |
| 40 | cross_source | 1.000 | Twilio | Software Engineer (L3) | greenhouse: Remote - India | himalayas:  | - | about address all apps are ask banking businessesand cards care comfort communications | same |
| 41 | near_duplicate_text | 1.000 | Palantir | Commercial Contracts Specialist | lever: New York, NY | lever: Palo Alto, CA | - | - | same |
| 42 | near_duplicate_text | 1.000 | Meridial | Garment Manufacturing QC Specialist - Freelance AI Trainer Project | greenhouse: Lesotho | greenhouse: Honduras | - | - | same: identical text; both tagged worldwide (Greenhouse office list), so eligibility matches |
| 43 | near_duplicate_text | 0.974 | Swiggy | Account Manager | smartrecruiters: Chennai, TN, IN | smartrecruiters: Guwahati, AS, IN | - | base days employees locations office respective their ways | same |
| 44 | near_duplicate_text | 0.993 | MongoDB | Manager, Site Reliability Engineering - Storage Layer Service | greenhouse: Dublin | greenhouse: Cork | dublin | cork | same |
| 45 | near_duplicate_text | 1.000 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: New York City, New York | greenhouse: Raleigh, North Carolina | - | - | same |
| 46 | near_duplicate_text | 0.930 | Amazon | Data Engineer, IN Data Engineering & Analytics | adzuna: India | adzuna: Bangalore, Karnataka | i key role | description | same |
| 47 | near_duplicate_text | 1.000 | Palantir | Forward Deployed Infrastructure Engineer - US Government | lever: New York, NY | lever: Washington, D.C. | - | - | same |
| 48 | near_duplicate_text | 1.000 | Fivetran | Senior Internal Communications Manager | greenhouse: Remote, Colorado, United States, AMER | greenhouse: Remote, Washington, United States, AMER | - | - | same |
| 49 | near_duplicate_text | 0.997 | Databricks | Sr. Forward Deployed Engineer (FDE) - Communications, Media, Entertainment & Games | greenhouse: Los Angeles, California | greenhouse: New York City, New York | - | sr | same |
| 50 | near_duplicate_text | 1.000 | Harvey | Associate Legal Engineer | ashby: Dallas | ashby: San Francisco | - | - | same |
