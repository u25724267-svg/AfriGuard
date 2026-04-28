"""Unit tests - review UI CLI helpers."""

from src.pipeline.dag import _review_ui_browser_url


def test_review_ui_browser_url_rewrites_all_interfaces_host():
    assert _review_ui_browser_url("0.0.0.0", 8000) == "http://127.0.0.1:8000"


def test_review_ui_browser_url_keeps_loopback_host():
    assert _review_ui_browser_url("127.0.0.1", 8001) == "http://127.0.0.1:8001"
