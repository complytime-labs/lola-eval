from metrics import compute, write_metrics_file


def test_compute_returns_int():
    assert isinstance(compute(), int)
    assert compute() >= 0
