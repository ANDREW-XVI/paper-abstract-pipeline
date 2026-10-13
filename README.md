# paper-abstract-pipeline

Two small command-line tools that find **real abstracts** and **recent papers** from open scholarly APIs, without inventing anything.

| Tool | Use it when | Input | Output |
|---|---|---|---|
| `find_abstracts.py` | You already have a list of papers (title + DOI/arXiv link) | CSV | Same CSV + `Abstract` + `Abstract Source` |
| `find_pi_papers.py` | You have researchers and want their newest papers + abstracts | CSV of University / Name / Research Focus | `papers.csv` + `status.csv` |

I built it to personalise outreach emails to professors: read one recent paper before you write.

## How it works

**Sources, in order** (the first one that returns a matching abstract wins):

1. **OpenAlex**: fast, no throttling with a free API key (main source for everything)
2. **arXiv**: for preprints, paced at 3 s per request as arXiv asks
3. **Crossref**: publisher DOIs that OpenAlex has no abstract for
4. **Semantic Scholar**: fallback only. It rate-limits (HTTP 429) heavily, so it fails fast instead of waiting
5. **Europe PMC**: biomedical papers
6. If nothing is found, the row says `Abstract not available – see <link>` and `Abstract Source = none`. Abstracts are never generated, shortened or guessed.

**A source's record is accepted only if its title matches** the paper you asked about (>= 80-92 % similarity).

**Finding the right researcher** (`find_pi_papers.py`). Names are ambiguous, so a profile must pass all three checks:
- **name**: same last name and a matching first name or initial
- **university**: the profile's affiliations name the university (distinctive words or acronym)
- **topic**: your "Research Focus" keywords appear in their recent titles/abstracts

If OpenAlex is rate-limited or finds fewer papers than requested, the tool falls back to Semantic Scholar (10-minute cooldown after a failure). Preprint and published versions of a paper are merged, and editorials, errata and books are dropped. Output is sorted newest first.

Everything is resumable: re-run the same command and finished rows are skipped.

## Setup

```bash
git clone <this repo> && cd paper-abstract-pipeline
pip install -r requirements.txt
export OPENALEX_API_KEY=...      # free: https://openalex.org (account -> API key)
export S2_API_KEY=...            # optional, raises Semantic Scholar limits
export CONTACT_EMAIL=you@example.com   # optional, sent in the User-Agent / Crossref polite pool
```
Keys are read from environment variables only. Never commit them (`.env` is git-ignored; see `.env.example`).

## Usage

```bash
# 1) abstracts for papers you already have
python find_abstracts.py --input examples/sample_papers.csv --output out_abstracts.csv --title-col "Paper title" --link-col Link

# 2) newest 3 papers (2024+) per researcher
python find_pi_papers.py --input examples/sample_pis.csv --out-dir out/
python find_pi_papers.py --input my_pis.csv --out-dir out/ --retry-failed   # redo SKIPPED / NO_MATCH
```
`status.csv` marks each researcher `OK`, `PARTIAL` (fewer than 3 papers or a missing abstract), `NO_MATCH` (no profile passed the checks) or `SKIPPED` (all sources were unavailable; re-run later).

## Known limitations (please read)

- **Same-name researchers can slip through.** The name, university and topic checks catch most of them, but a generic Research Focus ("computer vision", "machine learning") can let a namesake pass. Spot-check a sample of results before relying on them.
- **Merged profiles.** OpenAlex and Semantic Scholar sometimes merge two people. Low topic overlap triggers a per-paper topic filter, which can also drop a few genuine papers.
- **Coverage.** Very new papers and books often have no indexed abstract; some researchers are listed under an institution name that does not match what you typed (`NO_MATCH`).
- **Rate limits and costs.** OpenAlex's free key has a small daily budget; a few hundred researchers fit comfortably.
- Respect each API's terms of use. Abstracts remain the property of their publishers: use them for reading and research, not redistribution.

## Layout

```
find_abstracts.py        CLI: abstracts for a paper list
find_pi_papers.py        CLI: newest papers + abstracts per researcher
paper_abstracts/
  common.py              HTTP with pacing/retries, text helpers
  sources.py             one function per source, title-verified
  identity.py            name / university / topic checks
  pi_papers.py           OpenAlex-first, Semantic Scholar fallback
examples/                tiny sample inputs
```

MIT licensed.
