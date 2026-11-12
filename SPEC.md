# Bifrost: Spec

Last updated: 2026-11-11. This is a living document. Change it when a decision changes, and log why in DECISIONS.md.

## What it does

Bifrost recommends fiction books from a reader's reading history (their "shelf") and gives a reason for each recommendation. It compares five recommender models on the same held-out data, then serves the results through a small API and a demo page.

## The question

When does book text (descriptions and reviews) help a recommender more than reader behaviour alone?

Hypothesis: text helps most for cold-start books, meaning books with very few reader interactions. This may turn out to be wrong, and I will report whichever result the data gives.

## Data (all public)

- UCSD Goodreads Book Graph: a filtered fiction subset, starting with one or two genres.
- Open Library, to match titles from my own reading history.
- My own Book Tracker CSV, for a personal demo.

## Models (five, behind one shared interface)

1. Popularity baseline: recommend the most-read books.
2. Item-kNN: "readers who read X also read Y".
3. Matrix factorization (ALS or BPR).
4. Text-embedding model: score books by text similarity to the reader's shelf.
5. Hybrid: blend collaborative and text scores.

## Evaluation

- Per-user temporal split: train on earlier books, test on later ones.
- Metrics: NDCG@20, Recall@20, catalog coverage, mean popularity of recommendations.
- Slice results by how many interactions each test book has (cold-start versus popular).
- Bootstrap 95% confidence intervals over users.
- Tune on the validation split. Run the test split once, at the end.

## Serving

- FastAPI with /recommend and /explain endpoints.
- Approximate nearest-neighbour index (HNSW).
- Latency target: p95 under 50 ms. This is a first guess and will be revised once I measure the baseline.

## Success criteria

- [ ] make data, make eval and make serve each work from a fresh clone
- [ ] A results table with confidence intervals for all five models
- [ ] At least one clear finding about cold-start books, or an honest negative result
- [ ] Tests and CI passing
- [ ] A live demo and a 2-minute video
- [ ] Every number on my resume can be reproduced with one command

## Non-goals

- No frontend beyond a Gradio demo page
- No user accounts or database server
- No pirated or copyrighted full-text book files
- No claims the data does not support

## Dates

- Dec 1, 2026: checkpoint. The data pipeline must run end to end, otherwise I switch the project to spoiler detection.
- Jan 18, 2027: resume-ready, before WaterlooWorks Cycle 1 Posting A closes (Jan 19, 9 a.m.).
