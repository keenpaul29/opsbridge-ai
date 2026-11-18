import pytest

from app.db import embedding_dim_error


@pytest.mark.parametrize(("actual", "expected"), [(768, 768), (None, 768)])
def test_matching_or_absent_column_is_fine(actual: int | None, expected: int):
    assert embedding_dim_error(actual, expected) is None


def test_a_stale_column_width_names_both_sizes_and_the_fix():
    message = embedding_dim_error(1536, 768)
    assert message is not None
    assert "vector(1536)" in message and "EMBEDDING_DIM=768" in message and "drop" in message
