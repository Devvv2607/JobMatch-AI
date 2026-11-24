# Out of scope

Things JobMatch deliberately does not do, and why. Recorded 2026-11-24.

| Not built | Why |
|---|---|
| Scraping job portals (LinkedIn, Indeed, Glassdoor, Naukri, Internshala, Wellfound and the like) | Their terms prohibit automated access, and scraped data breaks without notice. JobMatch uses official APIs, open datasets and public ATS endpoints only (see the README's source list). |
| Auto-apply | Applying on someone's behalf without their review conflicts with the "never invent" promise and with most sites' terms; a tailored resume is only ever offered for the user to submit. |
| Browser extension | A second client to build, review and keep secure, for no gain in relevance or verification. |
| Gmail / inbox sync | Reading a user's mailbox is a large privacy surface (OAuth scopes, storage, deletion) for a tracker convenience; the tracker takes manual input instead. |
| Billing | The project runs at zero cost by design; there is nothing to charge for. |
| Community features (comments, reviews, forums) | Moderation and abuse handling for a single-developer project; not part of the relevance or verification story. |
| Ghost-job signals from user reports | They need a large user base to be meaningful; structural signals computed from the postings themselves are used instead (see the backlog). |
| Meilisearch (or another search server) | Postgres + pgvector + bm25s already cover lexical and vector retrieval in one database, measured; another service would add memory and operations without a measured gain. |
