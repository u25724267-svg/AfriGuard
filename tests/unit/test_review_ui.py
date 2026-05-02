"""Unit tests - review UI routes."""

from fastapi.testclient import TestClient

from src.review.annotation_interface import app


def test_login_page_renders():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "AfriGuard" in response.text
    assert "reviewer_shona" in response.text
    assert "Admin Password" in response.text


def test_reviewer_can_login_without_password():
    client = TestClient(app)

    response = client.post(
        "/login",
        data={"reviewer_id": "reviewer_shona"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/review"


def test_admin_still_requires_password():
    client = TestClient(app)

    response = client.post(
        "/login",
        data={"reviewer_id": "admin"},
        follow_redirects=False,
    )

    assert response.status_code == 401
