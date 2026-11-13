# Decisions log

Every significant choice goes here. Each entry has the decision, the alternatives I rejected, why, and what would make me change my mind. This file is my interview notes.

## 2026-11-10: Python 3.12, managed with uv

- **Decision:** Use Python 3.12, with uv for the environment and dependencies.
- **Alternatives rejected:** pip with venv; conda; poetry.
- **Reason:** uv is fast, produces a lockfile (uv.lock) so anyone can recreate my exact environment, and handles the environment and dependencies in one tool.
- **Revisit if:** a key library, such as implicit, won't install on Apple Silicon. The fallback is a small BPR model written in PyTorch.

## 2026-11-10: Public datasets only

- **Decision:** Use only the UCSD Goodreads Book Graph, Open Library and my own Book Tracker export. No pirated book files.
- **Alternatives rejected:** Full-text books from LibGen or OceanofPDF.
- **Reason:** The repo is public, so a recruiter can see what it was built on. Pirated data creates legal risk for me, and the recommender doesn't need full book text, because descriptions and reviews are enough to answer the research question.
- **Revisit if:** I need full text for a later experiment. In that case I'd use public-domain books from Project Gutenberg.

## 2026-11-11: Renamed project to Bifrost

- **Decision:** Rename the project from Shelf-Aware to Bifrost (package name `bifrost`).
- **Alternatives rejected:** Shelf-Aware.
- **Reason:** I wanted for there to be a cool name not like shelf aware or anything
- **Revisit if:** Bifrost is a misleading name

## 2026-11-11: Positive interaction

- **Decision:** A positive interaction is any row with is_read = 1, whatever the rating. A book that was read but has rating = 0 still counts as positive, because 0 means "not rated", not "disliked". Rows with is_read = 0 are "to-read" shelvings, and I don't use them.
- **Alternatives rejected:** Every row, including to-read shelvings; rating > 0; rating >= 3; rating >= 4.
- **Reason:** About half the poetry rows (1,420,740, or 52.0%) are to-read shelvings with no rating. They only tell me someone wanted to read a book, not that they did. Every rated row is also a read row, so is_read = 1 keeps all the real reading: 1,313,610 rows (48.0%). Requiring rating > 0 would throw away 84,551 reads that simply weren't rated. People rate generously (73.8% of ratings are 4 or 5), so a rating cutoff mostly loses data: rating >= 4 keeps only 33.2% of rows.
- **Revisit if:** the 84,581 reads rated 1 or 2 (6.4% of reads) turn out to hurt the models, or I add a model that uses the rating value itself.

## 2026-11-11: Ordering timestamp

- **Decision:** Order each user's history by date_added. Break ties with date_updated, then book_id, so the order is always the same. If date_added is missing or can't be parsed, drop that row and log how many rows were dropped.
- **Alternatives rejected:** read_at; started_at; filling a missing date_added from date_updated.
- **Reason:** date_added is the only timestamp I can rely on: it is missing in 0 of 2,734,350 poetry rows, and every value falls between 2001 and 2017 (only 67 positives are dated before Goodreads launched in 2007). read_at is missing in 84.5% of rows and has impossible years like 0029 and 2558, and started_at is missing in 88.4%. The catch is that date_added is when someone shelved a book, not when they read it, so a batch of old reads shelved on one day all looks "new".
- **Revisit if:** another genre or my Book Tracker export has date_added missing in more than 1% of rows.

## 2026-11-11: Train, validation and test split

- **Decision:** For each user, sort their positives using the ordering above. The last positive goes to test, the second-to-last goes to validation, and everything before that goes to train. I tune on validation. For the one final test run, I train on train plus validation.
- **Alternatives rejected:** One global date cutoff for all users; a per-user 80/10/10 split by fraction.
- **Reason:** Users have few positives (median 2, 90th percentile 9), so a 10% slice is usually empty: a user with 5 positives would get half a book. Holding out the last two gives every evaluated user exactly one validation book and one test book. Exact ties are rare: only 82 of the 66,657 evaluated users (0.1%) have test and validation books with the same date_added to the second, and the tie-breaks settle them. Same-day ties are not rare: for 19,627 users (29.4%), the test and validation books were added on the same calendar day, so for them "last" often just means "last in a batch shelved together". The validation/train boundary is worse: 113 users (0.2%) tie to the second there and 25,592 (38.4%) tie by day. The earlier figure of 179 users (0.3%) counted ties to the second at either boundary.
- **Revisit if:** I need results where the model never sees the future. With this split, a model can train on books other users added after a test user's test book. A global date cutoff would fix that.

## 2026-11-11: Minimum user history

- **Decision:** A user needs at least 5 positives to be in validation and test, which leaves at least 3 books to train on. Users with fewer than 5 positives are not evaluated, but their positives stay in the training data.
- **Alternatives rejected:** At least 3 positives; at least 10 positives; removing users with fewer than 5 positives completely.
- **Reason:** 66,657 users (23.6% of readers) have 5 or more positives. With a minimum of 3, a user would have just 1 book left to train on. With a minimum of 10, only 27,912 users (9.9%) would be evaluated. I keep light users in training because they matter for cold start: dropping them would remove 29.4% of positives and leave 1,055 books with no reads at all.
- **Revisit if:** the models do better when light users are left out of training, or evaluating 66,657 users is too slow to tune with.

## Template for new entries

## YYYY-MM-DD: short title

- **Decision:**
- **Alternatives rejected:**
- **Reason:**
- **Revisit if:**
