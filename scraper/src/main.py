import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, field_validator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://books.toscrape.com/"
START_URL = urljoin(BASE_URL, "catalogue/page-1.html")
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/899Amr/task-api)"
TIMEOUT_SECONDS = 10
REQUEST_DELAY_SECONDS = 0.5
MAX_CATALOGUE_PAGES = 3

PROJECT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_DIR / "cache"
OUTPUT_DIR = PROJECT_DIR / "output"


class BookRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    product_url: HttpUrl
    price_text: str
    price_gbp: float
    availability_text: str
    rating_text: str
    description: str | None
    source_page: HttpUrl
    fetched_at: datetime

    @field_validator("title", "price_text", "availability_text", "rating_text")
    @classmethod
    def required_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("price_gbp")
    @classmethod
    def valid_price(cls, value: float) -> float:
        if value < 0:
            raise ValueError("must be non-negative")
        return round(value, 2)


def normalize_price(price_text: str) -> float:
    cleaned = price_text.strip().replace("£", "")
    return round(float(cleaned), 2)


def cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    name = Path(urlparse(url).path).stem or "index"
    return CACHE_DIR / f"{name}-{digest}.html"


class PoliteFetcher:
    def __init__(self) -> None:
        self.last_request_at = 0.0
        self.pages_fetched = 0
        self.cache_hits = 0

    def fetch(self, url: str) -> tuple[str, datetime]:
        path = cache_path(url)
        if path.exists():
            self.cache_hits += 1
            content = path.read_text(encoding="utf-8")
            fetched_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            print(f"CACHE HIT url={url} bytes={len(content.encode('utf-8'))}")
            return content, fetched_at

        for attempt in (1, 2):
            wait = REQUEST_DELAY_SECONDS - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    self.last_request_at = time.monotonic()
                    status = response.status
                    content = response.read()
                if status != 200:
                    raise HTTPError(url, status, "Unexpected status", {}, None)
                html = content.decode("utf-8")
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf-8")
                self.pages_fetched += 1
                print(f"FETCH url={url} status=200 bytes={len(content)}")
                return html, datetime.now(timezone.utc)
            except HTTPError as exc:
                self.last_request_at = time.monotonic()
                if exc.code in (403, 404) or exc.code < 500 or attempt == 2:
                    raise
            except (TimeoutError, URLError):
                self.last_request_at = time.monotonic()
                if attempt == 2:
                    raise
            time.sleep(1)
        raise RuntimeError(f"Unable to fetch {url}")


def discover_books(fetcher: PoliteFetcher) -> tuple[list[dict[str, str]], int]:
    page_url = START_URL
    discovered: list[dict[str, str]] = []
    pages = 0
    while page_url and pages < MAX_CATALOGUE_PAGES:
        html, _ = fetcher.fetch(page_url)
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("article.product_pod h3 a[href]"):
            discovered.append(
                {"product_url": urljoin(page_url, link["href"]), "source_page": page_url}
            )
        pages += 1
        next_link = soup.select_one("li.next a[href]")
        page_url = urljoin(page_url, next_link["href"]) if next_link else ""

    unique = {item["product_url"]: item for item in discovered}
    print(
        f"catalogue_pages={pages} discovered={len(discovered)} "
        f"unique_urls={len(unique)}"
    )
    return list(unique.values()), pages


def extract_raw_record(
    html: str, product_url: str, source_page: str, fetched_at: datetime
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    product = soup.select_one("div.product_main")
    if product is None:
        raise ValueError("product area not found")
    title = product.select_one("h1")
    price = product.select_one("p.price_color")
    availability = product.select_one("p.instock.availability")
    rating = product.select_one("p.star-rating")
    if None in (title, price, availability, rating):
        raise ValueError("required product field missing")
    rating_classes = [value for value in rating.get("class", []) if value != "star-rating"]
    description_node = soup.select_one("#product_description + p")
    description = description_node.get_text(" ", strip=True) if description_node else None
    return {
        "title": title.get_text(" ", strip=True),
        "product_url": product_url,
        "price_text": price.get_text(" ", strip=True),
        "availability_text": availability.get_text(" ", strip=True),
        "rating_text": rating_classes[0] if rating_classes else "",
        "description": description,
        "source_page": source_page,
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
    }


def validated_record(raw: dict[str, Any]) -> BookRecord:
    return BookRecord.model_validate({**raw, "price_gbp": normalize_price(raw["price_text"])})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run(include_failure: bool = False) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    fetcher = PoliteFetcher()
    candidates, catalogue_pages = discover_books(fetcher)
    if include_failure:
        candidates.append(
            {
                "product_url": urljoin(BASE_URL, "catalogue/deliberately-missing-book/index.html"),
                "source_page": START_URL,
            }
        )

    valid: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    failed_pages = 0
    first_raw: dict[str, Any] | None = None
    for candidate in candidates:
        url = candidate["product_url"]
        try:
            if "deliberately-missing-book" in url:
                raise HTTPError(url, 404, "Deliberate failure test", {}, None)
            html, fetched_at = fetcher.fetch(url)
            raw = extract_raw_record(html, url, candidate["source_page"], fetched_at)
            first_raw = first_raw or raw
            record = validated_record(raw)
            valid[str(record.product_url)] = record.model_dump(mode="json")
        except (HTTPError, URLError, TimeoutError, ValueError, ValidationError) as exc:
            failed_pages += 1
            errors.append({"product_url": url, "reason": str(exc)})
            print(f"SKIP url={url} reason={exc}")

    records = list(valid.values())
    write_json(OUTPUT_DIR / "books.json", records)
    write_json(OUTPUT_DIR / "errors.json", errors)
    duration = round(time.monotonic() - started_clock, 3)
    report = {
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "duration_seconds": duration,
        "catalogue_pages": catalogue_pages,
        "detail_pages": len(records),
        "pages_fetched": fetcher.pages_fetched,
        "cache_hits": fetcher.cache_hits,
        "valid_records": len(records),
        "invalid_records": len(errors),
        "failed_pages": failed_pages,
    }
    write_json(OUTPUT_DIR / "run-report.json", report)
    if first_raw:
        print(json.dumps(first_raw, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Polite Books to Scrape pipeline")
    parser.add_argument(
        "--test-failure",
        action="store_true",
        help="include one deliberate 404 to prove failure isolation",
    )
    args = parser.parse_args()
    report = run(args.test_failure)
    if report["valid_records"] != 60:
        raise SystemExit("Expected exactly 60 valid book records")


if __name__ == "__main__":
    main()
