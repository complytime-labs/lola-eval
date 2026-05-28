def range_sum(n: int) -> int:
    """Return the sum of integers 1..n inclusive."""
    total = 0
    for i in range(1, n):   # BUG: should be range(1, n + 1)
        total += i
    return total
