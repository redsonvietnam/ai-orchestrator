from w4_review_relay import self_tests

def test_w4_self_tests():
    result = self_tests()
    assert all(result.values()), result
