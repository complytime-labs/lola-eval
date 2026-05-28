from calc import range_sum


def test_range_sum_one():
    assert range_sum(1) == 1


def test_range_sum_five():
    assert range_sum(5) == 15  # 1+2+3+4+5


def test_range_sum_ten():
    assert range_sum(10) == 55  # 1+2+...+10
