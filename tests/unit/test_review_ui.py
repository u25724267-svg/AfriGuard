"""Unit tests - review UI routes."""

from fastapi.testclient import TestClient

from src.review.annotation_interface import app


def test_login_page_renders():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "AfriGuard" in response.text
    assert "reviewer_shona" in response.text
