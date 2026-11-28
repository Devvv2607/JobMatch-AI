## Phase 4: Evaluation
Goal: honest, reproducible relevance numbers. They become resume claims, so nothing is
assumed or rounded in our favour.
Gate: nothing below starts until I've given verdicts on the borderline duplicate pairs
and the tag samples.
1. Frozen snapshot of the job pool (ids, text, embeddings, BM25 index, version hashes)
   under an eval snapshot id. The full snapshot stays a local dump (not git). CI uses a
   committed reduced corpus: all pooled candidates + stratified distractors, at most
   25 MB compressed, with a hash manifest. `make eval` defaults to the reduced corpus;
   a flag runs the full one.
2. 25 fictional profiles (≈70% India: fresher / 1–3 yrs / 3–6 yrs; ML/AI, data,
   backend, full-stack, product/analyst; the rest US/EU and remote-seeking), each with
   realistic preferences, dealbreakers and a short query. No real person's data.
   eval/profiles/.
3. Pooling: top results of every variant (BM25, vector, hybrid RRF, each rerank
   candidate in ADR 0003, personalised), 20 pairs per profile = 500. Stratify by source
   and by engagement_type/poster_type, so Himalayas, gig work and agencies can't
   dominate. Record which variants surfaced each pair.
4. LLM judge: written rubric (0 irrelevant, 1 same field but wrong level/location/
   skills, 2 good with gaps, 3 apply today), structured output, data_class=public;
   respect Groq limits, fall back to Gemini; cache per pair; store label + reason.
5. Labelling tool (keyboard-driven): profile left, job right (title, company, location,
   eligibility, salary, stripped description). Keys 0–3, undo, skip, resume,
   progress, autosave every label.
   - BLIND first: 120 stratified pairs WITHOUT the judge's label; weighted Cohen's kappa
     is computed only on these.
   - Then the rest with the judge's label shown, judge-uncertain first.
   - label_source per pair: human_blind / human_with_suggestion / llm_only (report the
     counts honestly).
6. Metrics (`make eval`): per variant, NDCG@10, MRR, Recall@50 (over judged pairs,
   stated), 95% bootstrap CIs over profiles, a paired bootstrap/permutation test vs
   the keyword baseline; query-only vs profile-based; cold vs warm personalisation
   (simulated saved jobs); source_quality and "down-rank gig/agency" ablations
   (report, don't apply unless supported); latency p50/p95 per variant (estimate
   runtime first; my OK if over 5 min full CPU).
7. Choose the interactive rerank setting by rule (ADR 0003): the cheapest variant
   within 0.01 NDCG@10 of the best (or overlapping CI), lowest single-request p95 among
   those; state whether it meets 300 ms. Chunked multi-vector embeddings only if time
   allows.
8. CI gate: a fast eval subset on the reduced corpus fails if NDCG@10 drops more than
   0.02 from the committed baseline.
9. Reports: eval/reports/<date>-<commit>.md/.json (all numbers, snapshot id, label
   counts by source, kappa, exact commands). docs/claims.md maps each resume claim →
   number → command → date, and proposes corrected wording if a claim isn't
   supported.
10. HN "Who is hiring" stays postponed until after Phase 4.
Stop when the labelling tool is ready: the one command to start it, how to resume,
expected label counts (blind vs with suggestion), an estimate of my labelling time,
and confirmation that it autosaves.
