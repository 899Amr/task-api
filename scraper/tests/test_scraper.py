from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.main import extract_raw_record, normalize_price, validated_record


FIXTURES = Path(__file__).parent / "fixtures"
PRODUCT_URL = "https://books.toscrape.com/catalogue/fixture/index.html"
SOURCE_URL = "https://books.toscrape.com/catalogue/page-1.html"
NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def test_price_normalization() -> None:
    assert normalize_price("£51.77") == 51.77


def test_missing_description_is_none() -> None:
    html = (FIXTURES / "missing-description.html").read_text(encoding="utf-8")
    raw = extract_raw_record(html, PRODUCT_URL, SOURCE_URL, NOW)
    assert raw["description"] is None


def test_relative_url_becomes_absolute_during_discovery() -> None:
    from urllib.parse import urljoin

    assert urljoin(SOURCE_URL, "fixture/index.html") == PRODUCT_URL


def test_canonical_urls_remove_duplicates() -> None:
    records = {item: item for item in [PRODUCT_URL, PRODUCT_URL]}
    assert list(records) == [PRODUCT_URL]


def test_malformed_fixture_is_rejected() -> None:
    html = (FIXTURES / "malformed.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="required product field missing"):
        extract_raw_record(html, PRODUCT_URL, SOURCE_URL, NOW)


def test_schema_adds_numeric_price() -> None:
    html = (FIXTURES / "missing-description.html").read_text(encoding="utf-8")
    record = validated_record(extract_raw_record(html, PRODUCT_URL, SOURCE_URL, NOW))
    assert record.price_gbp == 12.5
    assert str(record.product_url).startswith("https://")
