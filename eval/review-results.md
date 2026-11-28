# Owner review results

Verdicts given by the project owner on the spot-check sheets in `eval/review/` (gitignored:
they quote job postings). This file records ids, scores, merge reasons and verdicts only.
Sheets: `backend/scripts/spot_checks.py`, seed 11, pool of 2026-11-24/25.

## 1. Duplicates: 20 random merged pairs (verdicts 2026-11-25)

Rule: city/territory variants of one role = same. Score: Jaccard (near_duplicate_text) or containment of the shorter text (cross_source).

| # | kept id | hidden id | company | reason | score | verdict |
|---:|---|---|---|---|---:|---|
| 1 | `90540b70-df4f-4608-ac72-7116eba72cf2` | `a6839126-d9c5-451c-af94-29c518daad86` | Canonical | cross_source | 1.000 | same |
| 2 | `43ef737a-39b4-4855-8bdc-dac1e8ccfef7` | `c9bb423e-d084-40b3-a2e4-2cfe65929540` | Kong | near_duplicate_text | 1.000 | same |
| 3 | `3104982e-badb-4d5a-a206-6cffd28fd6fa` | `a9bd795e-d7f7-4912-a1eb-387458f4a451` | Palantir | near_duplicate_text | 0.978 | same |
| 4 | `4c195caa-9a07-4564-aa03-6be053e12fe8` | `a67d399b-7ee2-4484-bad3-3b1821c2b267` | Fivetran | near_duplicate_text | 0.967 | same |
| 5 | `7f845dee-b82e-43a4-83ea-30700a30133e` | `b7c418d9-5acd-4e8d-8862-8fb5364dab8c` | Swiggy | near_duplicate_text | 1.000 | same |
| 6 | `d2ef27ec-4983-44d1-ab63-33aca05be793` | `d511ef18-56ec-4f53-8fa0-e5784a415bb6` | Databricks | near_duplicate_text | 1.000 | same |
| 7 | `1750f74f-26ad-43a9-8027-f3f60334af83` | `4a36f32c-4c2d-477c-8936-92d4bba35713` | Swiggy | near_duplicate_text | 0.974 | same |
| 8 | `256f005e-ec45-4120-b615-06ad2d3efb87` | `49640607-a835-4b3b-ab70-e78386d1fc52` | Coinbase | cross_source | 0.978 | same |
| 9 | `1750f74f-26ad-43a9-8027-f3f60334af83` | `b8299d75-74d6-46fc-b6f8-205dbe41468e` | Swiggy | near_duplicate_text | 1.000 | same |
| 10 | `f0c98ed5-d3e9-4ff4-9e02-5e85a317eca8` | `ab8ee235-9f08-4868-9b32-b1f125c5ebbf` | Netomi | cross_source | 1.000 | same |
| 11 | `2ade156a-dc94-45b0-9d15-43c792f657a4` | `e2163632-bb12-4067-8475-df44ee2867a3` | Databricks | near_duplicate_text | 0.951 | same |
| 12 | `318445a7-1ba2-4a20-a141-f6c3c2f7b8df` | `dcce2529-ad9a-40dd-94c1-881cee87514f` | Palantir | near_duplicate_text | 1.000 | same |
| 13 | `87259e2d-ea35-491f-af6a-8aa5f2c7205c` | `49ba4ba3-3726-4ff0-b3a9-9dc7ee67b0b1` | Databricks | near_duplicate_text | 1.000 | same |
| 14 | `2881b0ee-d2c9-4178-8422-678211fb3a81` | `27ffeb4a-471e-4220-8507-a376d99d1ad1` | Fivetran | near_duplicate_text | 1.000 | same |
| 15 | `35c0b16d-bc69-4b21-8e9d-b2a2462bdaf8` | `a5cdcfd8-d321-4f8e-b6a0-cdca416b4ce0` | MongoDB | near_duplicate_text | 0.982 | same |
| 16 | `5918d6d7-eaa4-4f2b-83d7-36df897efcc7` | `6e65675e-4231-4cf2-84f4-ffa7d49f4e90` | LangChain | near_duplicate_text | 0.975 | same |
| 17 | `d598e3bb-0a73-4284-977f-c1c1ae5a4fe1` | `3a61652f-acf2-4a69-8d88-070353958fae` | Datadog | near_duplicate_text | 1.000 | same |
| 18 | `46973db4-29e1-48d1-9634-069e1286cc6e` | `26716407-51a9-4256-85a5-a675699b00c9` | Okta | near_duplicate_text | 0.977 | same |
| 19 | `1ce2d335-1ad9-471c-bb40-d90aef7cee2b` | `c0d4063f-fe24-4a7d-836d-520440340dc6` | Databricks | near_duplicate_text | 1.000 | same |
| 20 | `43967273-9de0-4705-96df-c7a5b5d0737e` | `f57da487-4f85-4c99-a249-ae44d4a44aa7` | Gururo | near_duplicate_text | 1.000 | same |

Totals: 20 same, 0 different, 0 unsure (17 near_duplicate_text + 3 cross_source). Threshold 0.90 kept.

## 2. Duplicates: borderline pairs, Jaccard 0.90-0.95 (verdicts 2026-11-25)

| # | kept id | hidden id | company | reason | score | verdict |
|---:|---|---|---|---|---:|---|
| 1 | `bbbf1a12-3513-476c-831d-ae3e9f157c67` | `d665fa6d-f9a9-42a1-a316-f67d2331b9f5` | Jobdost | near_duplicate_text | 0.925 | same |
| 2 | `01eff5db-31d7-4cd1-abb9-a25fbe948adb` | `c3136ea5-040a-477a-9a2b-684d5bd3b67b` | Swiggy | near_duplicate_text | 0.949 | same |
| 3 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `211637a5-760b-45de-a46a-b8c8132016de` | MongoDB | near_duplicate_text | 0.913 | same |
| 4 | `700fa7f2-d661-462e-9f82-62cd51dcf0b1` | `f39bb7ea-a3d3-49b2-9826-114dd8eec283` | Tailscale | near_duplicate_text | 0.934 | same |
| 5 | `725c9c6e-36bb-45ff-af9c-f6e9a61c298e` | `84da6f0a-56ea-4b2e-ad24-43d47e2e762c` | Palantir | near_duplicate_text | 0.934 | same |
| 6 | `a700ce30-a5c1-4ca0-86a0-0f778ff50109` | `b4958bed-4435-4d83-877e-d13348d778d0` | Stripe | near_duplicate_text | 0.935 | different (verdict 2026-11-25 after the full-text diff: separate requisitions 6717520 / 8261012, posted 18 months apart; the older names a specific team). Unmerged; kept apart in backend/app/ingest/data/not_duplicates.yaml |
| 7 | `2fe64ce1-96b1-4599-9fe5-6418b9ad1c5a` | `495d6b12-a605-4517-a37f-b0a47e389a9b` | Datadog | near_duplicate_text | 0.903 | same |
| 8 | `1f4086fe-00de-4aae-b330-76d525ba8b3d` | `5f404f52-af08-450c-a088-b84612577c7c` | Databricks | near_duplicate_text | 0.901 | same |
| 9 | `54cd5f0d-30d3-43d2-85d1-18431cb23430` | `70693f49-6de7-4449-a02a-246f15edb42f` | Harvey | near_duplicate_text | 0.919 | same |
| 10 | `6a82741a-ba26-45ce-8f5b-936e2080931c` | `c90f5cf6-33b1-45aa-bcff-386747c5ca3e` | Elastic | near_duplicate_text | 0.906 | same |

Totals: 9 same, 1 different.

## 3. Duplicates: chain-merged pairs, below 0.90 against the kept job (verdicts 2026-11-25)

| # | kept id | hidden id | company | reason | score vs kept | verdict |
|---:|---|---|---|---|---:|---|
| 11 | `48237fbe-91fe-4f65-a621-03305443f672` | `335560d9-951b-4447-ae53-5ad1e54239c6` | AlphaSense | near_duplicate_text | 0.447 | different (false merge) |
| 12 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `f5153500-acf4-43bc-ba0b-1af3b0dfa2bc` | MongoDB | near_duplicate_text | 0.881 | same |
| 13 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `187dfbc9-af0f-413e-bcc7-7136ccc3559a` | MongoDB | near_duplicate_text | 0.884 | same |
| 14 | `8ec35477-85b5-4039-b716-82d1b92bd04b` | `dcefc182-af37-45bc-b0f0-7f2097d5c5f8` | Palantir | near_duplicate_text | 0.891 | same |
| 15 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `39c17f0f-0a77-47ff-9f13-2350e320bf87` | MongoDB | near_duplicate_text | 0.892 | same |
| 16 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `1004babb-881b-4de7-92ee-2aaf54c50f89` | MongoDB | near_duplicate_text | 0.894 | same |

Totals: 5 same, 1 different. Rule change that follows: a posting joins a chained group only if it also scores >= 0.85 against the group's canonical posting (see docs/decisions/log.md, 2026-11-25).

### Precision, per sample (not blended): text and cross-source merges only

These figures cover only the text pass (near_duplicate_text and cross_source merges).
They never covered the exact title+location pass, which merged 423 pairs without
reading the text (removed 2026-11-25, see section 6), or content_hash merges.

The borderline and chain samples were drawn deliberately from the low-score tail, so the
three are reported separately and never pooled into one percentage.

| sample (text and cross-source merges only) | drawn from | same | different | precision (merges judged correct) |
|---|---|---:|---:|---|
| random 20 | all 733 active text / cross-source merges, 2026-11-24 | 20 | 0 | 20/20 |
| borderline 10 | near_duplicate_text, Jaccard 0.90-0.95 vs kept, one per company | 9 | 1 | 9/10 |
| chain 6 | every merge scoring < 0.90 vs the kept job | 5 | 1 | 5/6 |

Not covered by any sample: the 423 exact `title_location` merges (same company, same
normalised title and location, no text check). That pass was removed on 2026-11-25
(section 6); a sample over every remaining merge reason is section 6's.

## 4. Himalayas: 30 random jobs we mark eligible for India (verdicts 2026-11-25)

| # | job id | our scope | verdict |
|---:|---|---|---|
| 1 | `c4a8f075-2352-445d-9fe5-3e886b1973e7` | listed | right |
| 2 | `0c9d00ba-af90-4977-983e-d3d11d9d629f` | listed | right |
| 3 | `b8b60f9c-c862-42ca-be79-7de2272ecce8` | listed | right |
| 4 | `7a83286d-ded6-4f3e-b04a-c543e8c17956` | listed | right |
| 5 | `8c98f81e-7f59-4488-ad94-feaec54d56e4` | listed | right |
| 6 | `cb6cf27e-f660-48d0-bb71-f3120cd8db95` | listed | right |
| 7 | `e6283937-9a73-4efc-9f41-5a27aa70acb5` | listed | right |
| 8 | `bea4c4f7-44e2-47af-bf7f-636db36c6542` | listed | right |
| 9 | `ca19e577-4e46-47f8-92fa-2d5dcfcdf796` | listed | right |
| 10 | `2f982934-1256-4e0c-bdd5-58405af6278f` | listed | right |
| 11 | `c1286ed6-67b1-4f29-aee9-d646476f5e39` | listed | right |
| 12 | `04241f84-60d3-4f83-aacd-d146da4b1495` | listed | right |
| 13 | `a25fd37a-150b-4330-8a92-9119949afa13` | listed | right |
| 14 | `12e55617-9b30-4ae9-afd0-2b4daf00a64c` | listed | right |
| 15 | `11f9bf20-0d5c-48e5-8712-b11d6a00634c` | listed | right |
| 16 | `0aab2a30-84cc-4b7d-af0c-77a873268e4a` | listed | right |
| 17 | `3aac64c3-4442-4250-ad83-74b4abbe0331` | listed | right |
| 18 | `4a8bd55f-1b6a-41cb-9d7e-28b532cc663f` | listed | right |
| 19 | `ba0b6482-5f77-4ef4-b8a1-d93087161866` | listed | right |
| 20 | `092dff19-bbf0-4615-8432-9d89fb2fa0e9` | listed | right |
| 21 | `f345afce-1458-4f27-a10a-e132935bc42d` | listed | right |
| 22 | `8f9ece88-b8b3-4bf5-9654-71641409a2a6` | listed | right |
| 23 | `647c83cc-4106-4397-86b7-1245697119b8` | listed | right |
| 24 | `8922b507-13ae-4c16-9a48-334abcd7b970` | listed | right |
| 25 | `b780599a-80f4-43df-af1c-f2025f694d65` | listed | right |
| 26 | `3c0171a2-d1db-459d-970f-9b483deee4ed` | listed | right |
| 27 | `9f782501-839c-4d16-8331-b0aa5cc632db` | listed | right |
| 28 | `48054b3b-110a-4f66-bc96-40f729cd6922` | listed | right |
| 29 | `c6cb3b6b-40bc-4897-aa13-fbbd67cc87e6` | listed | right |
| 30 | `59c5de1e-60c2-42df-826a-bf61a023f5de` | listed | right |

Totals: 30 right, 0 wrong.

## 5. Engagement and poster tags: 15 random jobs per value (verdicts 2026-11-25)

Verdict per row as the owner gave it; "no comment" rows were accepted within the sheet's overall verdict.

### engagement_type = freelance_gig (sample of 15 from 1,608)

| # | job id | company | source | verdict |
|---:|---|---|---|---|
| 1 | `94b7a5a5-3ab5-46a2-929f-51d17c3c2113` | mercor | himalayas | right |
| 2 | `b3370ac2-79e0-4737-9cf1-4dbec85f280e` | Meridial | greenhouse | right |
| 3 | `feb38fd3-41c8-402d-bc7c-3faf860ccc97` | Meridial | greenhouse | right |
| 4 | `98765e4c-9382-49e5-b6b6-c3ebed447718` | mercor | himalayas | right |
| 5 | `94adfacf-bfc5-4707-a36f-00a363a53fc6` | Meridial | greenhouse | right |
| 6 | `a4326313-8de3-4740-89cd-d39634714d34` | Invisible Technologies | himalayas | right |
| 7 | `bd181702-2503-462e-9c1e-7015f7e38d36` | Invisible Technologies | himalayas | right |
| 8 | `3ec9cd10-bbe9-4e36-83d9-c4f60a29c057` | Meridial | greenhouse | right |
| 9 | `3dadf293-f378-43dd-888b-f802d0d53181` | AIDA Recruitment | himalayas | wrong: contract + staffing_agency (agency subcontract, 6-9 months), not a gig |
| 10 | `a546d1f1-8e6c-4bea-84ec-a7cb5daa394c` | Meridial | greenhouse | right |
| 11 | `9b594208-5a04-4b1f-9589-1c4051e1683d` | Meridial | greenhouse | right |
| 12 | `ce784511-385f-42ca-9ae7-02a10e5bd8b5` | Meridial | greenhouse | right |
| 13 | `c80ca180-daba-4c8f-aaed-30bab548711c` | mercor | himalayas | right |
| 14 | `3e44a4cd-259e-4989-af53-e448e73d1f5b` | Meridial | greenhouse | right |
| 15 | `2034b430-6f9b-4883-b3b9-adeb1b63c704` | Invisible Technologies | himalayas | right |

Totals: 14 right, 1 wrong.

### engagement_type = contract (sample of 15 from 812)

| # | job id | company | source | verdict |
|---:|---|---|---|---|
| 1 | `96ce9d81-fc61-4fa3-9c73-eb95c3d7a4dd` | micro1 | himalayas | wrong: freelance_gig (AI-data vendor) |
| 2 | `66d818bb-2935-47f9-84ec-71fe50b62ffe` | Lifted (an Upwork Company) | himalayas | wrong: freelance_gig ("help train AI") |
| 3 | `330a7fee-08cd-47bf-a0d3-9e23381b8fdc` | Pocket FM | lever | no comment |
| 4 | `1d86adac-0abe-46dd-a688-a3feeccaa603` | Welo Global | himalayas | wrong: freelance_gig (Talent Hub) |
| 5 | `ae9cc47a-9ff3-4f73-a863-56beacabad7f` | Figma | greenhouse | check: what did the source field say? |
| 6 | `dfdd660d-d16b-4bc5-aecc-f2f7cbb61c4f` | Global University Systems (GUS) | himalayas | no comment |
| 7 | `cd6d29a8-e7ce-43b9-9f7d-d089041c0103` | Study.com | himalayas | no comment |
| 8 | `11c9bb89-84ab-45e3-b575-c54cff913269` | IMAV Learning Academy | himalayas | wrong: freelance_gig (commission-only partnership) |
| 9 | `c2a241ab-0417-44b2-80be-370c4bb03f7f` | Your Personal AI | himalayas | wrong: freelance_gig (voice recorders) |
| 10 | `84d4d3bd-08ce-4b19-8c9c-4084a50d8037` | micro1 | himalayas | wrong: freelance_gig (AI-data vendor) |
| 11 | `981d8969-492a-4dca-a6c0-11e866aac31c` | micro1 | himalayas | wrong: freelance_gig (AI-data vendor) |
| 12 | `d54bae87-7927-47ae-84c5-74fbfdf14ec1` | micro1 | himalayas | wrong: freelance_gig (AI-data vendor) |
| 13 | `ef28375c-dca2-4591-8e3c-dd54e2bf0cc5` | Welo Global | himalayas | wrong: freelance_gig (Talent Hub) |
| 14 | `c71c96da-5980-42ac-9240-99f7af8f245b` | Tracklings | himalayas | no comment |
| 15 | `d4d54a5b-bdee-4ce4-a3b0-a1040df3c41f` | micro1 | himalayas | wrong: freelance_gig (AI-data vendor) |

Totals: owner: "weak, ~9/15 should be freelance_gig". Rows matching the vendors and phrases the owner named: 10 (marked); #5 to check.

### engagement_type = part_time (sample of 15 from 72)

| # | job id | company | source | verdict |
|---:|---|---|---|---|
| 1 | `57b52684-d3d3-4109-b6b9-4a9f3ccb52ed` | iCertifi | himalayas | right |
| 2 | `01c81158-2a9d-4324-b880-8f845b309031` | Quantum Strides LLC | himalayas | right |
| 3 | `f0bd21a2-0500-4efd-8236-6fa0aadd2e0e` | TechBiz Global | himalayas | engagement right; poster wrong: staffing_agency |
| 4 | `10f48c31-9771-4a04-9faf-8ebd44e2a9ec` | Sudan Vision 2030 | himalayas | right |
| 5 | `0bab5440-307d-4c6f-9010-cf1dbc967bf7` | Revvity | himalayas | right |
| 6 | `0a9d2680-2784-4d12-bd42-cd0daa3ef6c4` | Outsourcey | himalayas | right |
| 7 | `67c640ff-b9c0-4d67-b574-828cbbb4f0e9` | One World Global Services | himalayas | right |
| 8 | `752533c3-cf1c-4460-9b5f-5f60deb2bb5a` | Müller`s Solutions | himalayas | right |
| 9 | `04dea37b-e7e7-4af9-8bb6-d94445ac8e04` | Vulcury | himalayas | right |
| 10 | `a12a64da-98cb-435e-89fc-297a919bbc18` | Staff Outsource Solutions | himalayas | engagement right; poster wrong: staffing_agency |
| 11 | `752194d1-0377-4c53-b55f-e74972540a62` | Bajaj Allianz Life Insurance Co. Ltd. | himalayas | right |
| 12 | `fa592a17-1f93-4a8b-92d9-a441fd669097` | SAPSOL Technologies Inc. | himalayas | right |
| 13 | `7229e4df-e711-46c5-86e0-c1d3e4308997` | PHASTAR | himalayas | right |
| 14 | `874270fe-4e3a-46c4-b278-2a9a45088c06` | SAPSOL Technologies Inc. | himalayas | right |
| 15 | `b24f43c5-e618-4b35-8d7c-562606a508f0` | HereNow | himalayas | right |

Totals: engagement 15 right; poster 2 wrong.

### engagement_type = internship (sample of 15 from 368)

| # | job id | company | source | verdict |
|---:|---|---|---|---|
| 1 | `4680479e-bf34-49ca-b8fe-6aa950a8a594` | Cloud Counselage Pvt Ltd | himalayas | right |
| 2 | `b53811eb-1043-4c68-ac7b-0b4369388685` | Databricks | greenhouse | right |
| 3 | `4f66d979-3b92-4fe4-9c78-d4455967ecfa` | Drivetrain | lever | right |
| 4 | `df3343bd-3988-4cc7-87ee-102cea26965a` | Cloud Counselage Pvt Ltd | himalayas | right |
| 5 | `68d1ba06-15c1-4b08-8325-0da76360292f` | Weekday AI | himalayas | right |
| 6 | `ae87bad1-4fa9-4986-a110-676c33587a9a` | Gemini | greenhouse | right |
| 7 | `0108b5a6-6428-4c89-91a9-0794dcf938e1` | Instawork | greenhouse | right |
| 8 | `e4b99722-067f-48a7-8045-22067c683673` | Coinbase | greenhouse | right |
| 9 | `1dbfc104-fad2-4929-99cd-d58571a57dac` | MongoDB | greenhouse | right |
| 10 | `a4a154aa-dfc1-47e1-957c-5d32aaea428e` | Databricks | greenhouse | right |
| 11 | `e2fb5f60-6fa7-4e2a-8b15-679ed1663356` | Instawork | greenhouse | right |
| 12 | `5fb32b86-31eb-4b4a-95b0-9084f38845df` | Car IQ | himalayas | right |
| 13 | `90e3f375-7d1d-4105-9062-98c105704bca` | Dazeinfo | himalayas | unclear (fine either way) |
| 14 | `c3c99e30-1707-43fd-b32e-bd80a61a02b4` | IIDE | himalayas | right |
| 15 | `1d5916c6-9cd1-4b19-b33b-ac5478ac1e84` | Palantir | lever | right |

Totals: 15 right (1 unclear).

### poster_type = staffing_agency (sample of 15 from 246)

| # | job id | company | source | verdict |
|---:|---|---|---|---|
| 1 | `b9e99289-59da-4f2e-8518-47111458a794` | Aura Recruitment Solutions | himalayas | right |
| 2 | `38d5bd37-ea77-494e-97fe-c08f49a0e1e2` | Pavago | himalayas | right |
| 3 | `4dd951c5-c08e-4b3a-96f0-94599e68b5ac` | MhyMatch | himalayas | right |
| 4 | `cb795f8d-e0ed-4142-9f0c-a863655a4b36` | Mintskill HR Solutions LLP | himalayas | right |
| 5 | `2fb6e3fe-0189-4192-8cda-0a7813372e78` | HYPR Service | himalayas | right |
| 6 | `83dc957e-58a5-4b79-bf41-12e3b75bd4bd` | SUNDAZE Digital | himalayas | right |
| 7 | `435dc622-d46d-4515-bd48-30a5750a8c5d` | Prokta HR Solutions | himalayas | right |
| 8 | `0a3cf341-5235-4af9-9827-f666df91d40a` | The supreme consultancy | adzuna | right |
| 9 | `1382c954-cf72-4300-8e83-f6ccb1201505` | Fresh Prints | himalayas | right |
| 10 | `905a2904-9d33-4e39-bf95-ec8e679f09a5` | David Kennedy Recruitment | himalayas | right |
| 11 | `cc9b5306-e8de-4e07-a677-06eef6f881d6` | HYPR Service | himalayas | right |
| 12 | `17aaefcb-efe5-4eb0-9b56-163b66032cf0` | Huzzle | adzuna | right |
| 13 | `62a08c08-266b-4a82-9d5f-5c2073a10e1c` | JF Talent Consulting Group (Global) | himalayas | right |
| 14 | `e1450ea8-2e43-4dd0-b3d6-cba4181707d5` | G2i Inc. | himalayas | right |
| 15 | `478a3bd1-c338-4396-bd74-f049d8c65e9a` | MM Staffing & Career Consultants | adzuna | right |

Totals: 15 right, 0 wrong.

Recall gaps the owner saw outside the samples (poster_type): TechBiz Global ("we provide recruitment services... one of our client's"), Staff Outsource Solutions, AIDA Recruitment ("For our client").

## 6. Exact title+location pass removed; sample over all merge reasons (2026-11-25)

Owner decision 2026-11-25: a same-company, same-title, same-location pair merges only
under the text rule (same source: Jaccard >= 0.97; different sources: containment
>= 0.60 as before), never on title and location alone. Applied to the live pool with
`python -m app.ingest.cli dedup` after `make backup`:

| fate of the 423 title_location merges | count |
|---|---:|
| unmerged (now separate jobs) | 351 |
| merged again by the text pass, same kept job | 59 |
| merged again by the text pass, another kept job | 13 |

The 351 unmerged by Jaccard against their old kept job: < 0.50: 220, 0.50-0.90: 75,
0.90-0.97: 49, >= 0.97: 7 (all 7 have different work eligibility from the old kept job,
e.g. Cloudflare "Inside Sales Representative" AE vs GB/PT, which the text pass never
merges). Elsewhere: 4 postings newly merged by the text pass, 2 text merges and 3
content_hash merges point at a different kept job. Merges after: 990 (content_hash 97,
near_duplicate_text 715, cross_source 178), was 1,337.

Sample for verdicts: `eval/review/duplicates-all.md`, 20 random pairs from all 990
merges (every reason), seed 25: near_duplicate_text 18, cross_source 1, content_hash 1.
Verdicts 2026-11-25:

| # | kept id | hidden id | company | reason | score | verdict |
|---:|---|---|---|---|---:|---|
| 1 | `728bb1a7-b347-4b2d-9b42-df07a946c8e9` | `64eb979c-3c33-4462-b91a-d1b4120b6d9d` | Harvey | near_duplicate_text | 0.994 | same |
| 2 | `00af96d9-6c31-46cc-9505-71a71541d709` | `cfc7510f-faf5-4d9f-be76-b2985b67d863` | Harvey | near_duplicate_text | 0.996 | same |
| 3 | `d24d958b-4946-4c49-bb33-7d4c29de4553` | `f48369f2-581b-4f6b-a16f-9a3bef9d85d0` | OpenAI | near_duplicate_text | 0.961 | same |
| 4 | `a7c538e7-6cc5-4a3a-b28c-1c8fd490bae6` | `e1e15c73-896a-4317-b218-b1a80780e443` | Timble Technologies | near_duplicate_text | 1.000 | same |
| 5 | `d9c9f0e5-ec47-4a15-af16-8229e6509009` | `054218eb-1950-414a-b0a3-6ee0a71bf4c9` | Harvey | near_duplicate_text | 1.000 | same |
| 6 | `52263f73-478d-4bc9-bd2c-71ea602958af` | `3e1ee214-4f82-4843-8eda-0c47a6cdfc88` | Okta | near_duplicate_text | 1.000 | same |
| 7 | `eeb3167e-3f2e-4c1f-9a31-1acbef5343fe` | `f5153500-acf4-43bc-ba0b-1af3b0dfa2bc` | MongoDB | near_duplicate_text | 0.881 | same |
| 8 | `3e70bdb1-db50-453f-9f48-98454e262888` | `e66866d7-6d5e-442f-88eb-f57038e2b3f5` | Tailscale | near_duplicate_text | 0.988 | same |
| 9 | `49906112-5f61-4350-859c-1e0ce456b0ea` | `545fce90-2f10-48cc-8ce8-7c448ba6ed21` | Twilio | cross_source | 1.000 | same |
| 10 | `804f476c-a381-47ac-a2ef-29743dc236ea` | `a852bd4f-952b-46a4-b403-2f4822d6fadb` | Blitzy | near_duplicate_text | 1.000 | same |
| 11 | `fa514844-6bfa-4332-a16d-94541d334200` | `7ddf518d-52d9-4395-91c5-51877fedb3d1` | Blitzy | content_hash | 1.000 | same |
| 12 | `eaeab632-6f92-41db-8506-1fe9772acb1b` | `0dd4cbda-bfd4-454b-a0b0-e19968eea332` | AlphaSense | near_duplicate_text | 1.000 | same; kept job marked is_evergreen (talent community) |
| 13 | `72deffe2-e3b7-4b90-b827-9872149ad89a` | `e413f65b-e674-4c8e-aa8d-40e1ca8122e6` | Coinbase | near_duplicate_text | 0.976 | same, 2 openings: requisitions P77757 / P77758, first published 2026-07-30 / 2026-11-16, 38 sentences identical except the pay range top ($197,010 vs $218,900); same team and product, so the owner's rule gives same + openings_count |
| 14 | `b34f51f3-2d9c-415a-8a6c-7caf4db19ff9` | `fb962403-6e2b-46da-8c17-ca370a1ca648` | Databricks | near_duplicate_text | 0.976 | same role, 2 openings (different requisition codes, same text): openings_count = 2 |
| 15 | `783faa1a-8aae-4ac5-aeb3-fe52d0205c43` | `cbdb318d-e922-4ede-9743-5fa3e5caf825` | Mixpanel | near_duplicate_text | 1.000 | same |
| 16 | `449d0d0c-5b07-4e73-ae06-f56098cffb84` | `488b00fb-898b-4c3a-b17e-cade287e4481` | Palantir | near_duplicate_text | 1.000 | same |
| 17 | `8f95fee0-6e04-4e91-bdd4-39762b1ed7be` | `0b3f2c67-ac7b-4dff-bbb9-17795433dd8f` | Palantir | near_duplicate_text | 1.000 | same |
| 18 | `87259e2d-ea35-491f-af6a-8aa5f2c7205c` | `54871e99-bcca-4deb-9653-740bdd7a1f21` | Databricks | near_duplicate_text | 0.950 | same |
| 19 | `11f9b7f0-7552-478d-8a3f-819b4aa8f9cf` | `96f61e61-4837-4160-9c4a-c26598241c0f` | Databricks | near_duplicate_text | 0.963 | same |
| 20 | `54cd5f0d-30d3-43d2-85d1-18431cb23430` | `70693f49-6de7-4449-a02a-246f15edb42f` | Harvey | near_duplicate_text | 0.919 | same |

Totals: 20 same, 0 different (2 of them one role with 2 openings: #13, #14). `openings_count` (migration 0008) = the most postings of a merged job from one source at one normalised location; after dedup on 2026-11-25: 23,687 kept jobs with 1, 130 with 2, 10 with 3-6.

## 7. Tag sheet, second round (eval/review/tags.md, seed 11 after the first retag; verdicts 2026-11-25)

| sample | verdict | wrong rows (id, company: owner's verdict) |
|---|---|---|
| freelance_gig 15 | 15/15 | |
| internship 15 | 15/15 | |
| contract 15 | 13/15 | #2 `003e9fdf-fd1f-4eb4-b70a-b958b395e4b7` Aptura "Expression of Interest": AI-training gig, also is_evergreen; #3 `44aef810-d817-4e03-8c5c-abade0923793` Aptura "Junior Investment Banker": AI-training gig |
| part_time 15 | 13/15 | #8 `34db6213-3327-4f79-b4ad-6fb5b16f3ae0` Websidezone, #14 `8b0d370c-cab1-4665-aa7e-7ef3e4eb2fa8` FliqaIndia: "Internship" in the title wins over the source's part_time |
| staffing_agency 15 | 13/15 | #10 `7466d8a2-22c0-4fa7-89b6-8e18ec088a73` Jasya Consultancy, #14 `b105aaa6-ec5b-42a3-96a0-4077bb975d8e` Lingaro: employers (consultancies doing their own client work); #1 `11151636-1370-4bce-84dd-5c4ea1599b1d` Weekday AI: agency right, engagement freelance_gig ($175 one-time payment, video interview) |
| employer (Himalayas/Adzuna) 20 | 17/20 | #10 `740c959e-4d3f-465d-9434-ff093951e557` Qrata, #18 `691c80d7-a6a6-4670-880c-d29d53cd8a39` Madello Consulting (also is_evergreen): missed agencies; #1 `99bf4c5f-bdd6-4b37-b79b-e96c2a284ca0` company "Unknown"; #8 `defb03a9-1e88-4615-b711-56bfbfe2162f` Ambilio "AI Trainer": not AI-training gig work |

Rules changed after this review (docs/decisions/log.md, 2026-11-25), then `retag` on the
live pool (26,001 rows, expired included): employment_type 7, engagement_type 31,
poster_type 70, is_evergreen 59 changed. Unknown company: 19 active jobs, all Adzuna
("Unknown"); 2 of the 19 snippets name a domain (an e-mail or website), the other 17
nothing; the URL is an Adzuna details page. Not recovered; excluded from the eval pool.

Fresh check: eval/review/tags-recheck.md (seed 26, 10 contract and 10 staffing_agency
jobs not in tags.md). Verdicts: pending.
