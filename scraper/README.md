# The Polite Scraper

A deterministic Python pipeline using the standard HTTP library, Beautiful Soup, and Pydantic to fetch, cache, extract, normalize, validate, store, and report the first three catalogue pages from Books to Scrape.

## Target classification

- **Target:** `https://books.toscrape.com/`, a fictional bookstore that ToScrape explicitly provides as a safe web-scraping sandbox.
- **Scope:** exactly the first three catalogue pages, their 60 unique book detail pages, and no other catalogue pages.
- **Collected data:** title, canonical product URL, price, availability, rating, optional description, source page, and fetch time.
- **robots.txt result:** no robots file found. The missing file is not treated as permission; the sandbox's own description is the reason this limited practice run is appropriate.
- **Boundary:** I will not reuse this code on another site without checking its rules and terms first.

## Run in under five minutes

Requires Python 3.10+.

```bash
cd scraper
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
python src/main.py --test-failure
```

On macOS/Linux, activate with `source .venv/bin/activate`. The first run makes 63 polite requests and takes about 32 seconds. Later runs use the ignored `cache/` directory and finish quickly. Outputs are written to `output/books.json`, `output/errors.json`, and `output/run-report.json`.

## Record schema

| Field | Type | Rule |
| --- | --- | --- |
| `title` | string | required, non-empty |
| `product_url` | HTTPS URL | canonical identity |
| `price_text` | string | original scraped value |
| `price_gbp` | number | normalized, non-negative |
| `availability_text` | string | required |
| `rating_text` | string | required |
| `description` | string or null | never invented when missing |
| `source_page` | HTTPS URL | provenance |
| `fetched_at` | ISO-8601 datetime | provenance |

Pydantic validates every record before storage. Invalid records go to `errors.json` with their URL and reason. A dictionary keyed by canonical URL makes reruns idempotent.

## Politeness and resilience

- Every request identifies itself as `FlyRankInternship-A9/1.0` and links to this repository.
- Every request has a 10-second timeout and checks the HTTP status before parsing.
- Real requests are separated by at least 500 ms; cache hits make no network request.
- Timeouts, connection failures, and 5xx responses get one retry. A 403 or 404 is never retried.
- Each detail page is isolated, so one failure is logged and the other records survive.
- The `--test-failure` option adds one deliberate local test URL; it produces one 404 without harming the 60 good records.

This assignment needs no browser because the data is already present in the HTML returned by the server; browser automation would only add time and memory cost.

## Run evidence

```json
{
  "started_at": "2026-08-10T22:59:45.898431Z",
  "duration_seconds": 2.188,
  "catalogue_pages": 3,
  "detail_pages": 60,
  "pages_fetched": 0,
  "cache_hits": 63,
  "valid_records": 60,
  "invalid_records": 1,
  "failed_pages": 1
}
```

The committed `output/run-report.json` contains the full real report, including start time and duration.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The offline tests cover price normalization, absolute URLs, missing descriptions, duplicate canonical URLs, malformed HTML, and schema validation.

## Ethics

Prefer an official API whenever one exists. Never bypass a login, paywall, access block, or other protection. Collect only the minimum data needed for a clear purpose, identify automated clients honestly, and stop when a site's rules or response says no.

## Limitation

The selectors intentionally match this training sandbox. A real production scraper would need monitoring and a reviewed update whenever the target HTML structure changes.
