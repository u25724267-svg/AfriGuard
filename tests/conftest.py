"""
AfriGuard — Test configuration and shared fixtures.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.storage.db import Base


@pytest.fixture(scope="function")
def db_session():
    """Provide an in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_seed_texts():
    """A small set of sample text snippets for testing."""
    return [
        "Turai ta je kasuwa don siyan abinci don gidansu.",
        "Oluwaseun nilo iranlọwọ pẹlu iṣẹ ile-iwe rẹ.",
        "Thabo o ile a bua le molaodi wa kgoro ka ga tshwetso.",
        "Chimwemwe anapita ku msika kukagula chakudya.",
        "Alimu anafuna msaada wa kupata kazi mpya.",
        "Fatima ta yi aiki tuƙuru don samar da abinci.",
    ]
