from app.workers.resolve_normalize_worker import _normalization_failure_is_terminal


def test_normalization_partial_allowed_when_some_confirmed():
    assert not _normalization_failure_is_terminal(0, 0)
    assert _normalization_failure_is_terminal(2, 0)
    assert not _normalization_failure_is_terminal(1, 3)
