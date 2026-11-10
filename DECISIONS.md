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

## Template for new entries

## YYYY-MM-DD: short title

- **Decision:**
- **Alternatives rejected:**
- **Reason:**
- **Revisit if:**
