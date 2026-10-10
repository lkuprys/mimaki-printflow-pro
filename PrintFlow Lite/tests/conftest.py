import pytest


@pytest.fixture
def tmp(tmp_path):
    return str(tmp_path)
