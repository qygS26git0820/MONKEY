"""负向对照专用：断言的是**错误**行为。

因此即使 agent 把 calc.py 改对了，测试仍会失败——用于证明评测器真的在
检查断言，而不是"文件看起来改过了就判通过"。
"""

import unittest

from calc import add


class TestAdd(unittest.TestCase):
    def test_positive_matches_buggy_behaviour(self):
        self.assertEqual(add(2, 3), -1)

    def test_zero(self):
        self.assertEqual(add(0, 0), 0)


if __name__ == "__main__":
    unittest.main()
