import unittest

from scale import scale


class TestScale(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(scale(2), 6)

    def test_negative(self):
        self.assertEqual(scale(-1), -3)


if __name__ == "__main__":
    unittest.main()
