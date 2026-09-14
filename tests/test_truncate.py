"""截断的核心性质：交付给 agent 的文本必须能由 blob + 元数据逐字节重建。

这条性质的意义不是"内部实现正确"，而是"事后能还原 agent 当时看到的输入"。
只要它成立，观察者就不会被观测工具自身的截断引入偏差。

还有一条同样要紧、但机械重建覆盖不到的：截断必须真的截掉了东西。
head/tail 按字符切、保留量按字节卡时，多字节内容下很容易出现
"head 与 tail 合起来比原文还长"——交付文本比原文长、`elided_bytes`
为负、agent 读到"截断 -8193 字节"这种乱码标记。逐字节重建在这些情形下
依然成立，所以只有专门盯着数值的用例才拦得住它。
"""

import hashlib
import unittest

from harness.config import TraceOptions
from harness.trace import prepare_stream, reconstruct

from . import support

OPTS = TraceOptions(truncate_threshold_bytes=100, head_chars=10, tail_chars=10)


class PrepareStreamTest(unittest.TestCase):
    def setUp(self):
        self.blobs = self.enterContext(support.scratch_dir("blobs"))

    def test_under_threshold_is_passed_through_untouched(self):
        data = "a" * 30
        delivered, meta = prepare_stream(data, OPTS, self.blobs)

        self.assertEqual(data, delivered)
        self.assertFalse(meta["truncated"])
        self.assertEqual("none", meta["strategy"])
        self.assertEqual((30, 30, 0),
                         (meta["bytes_total"], meta["bytes_delivered"], meta["elided_bytes"]))
        self.assertEqual(meta["sha256_full"], meta["sha256_delivered"])
        self.assertIsNone(meta["blob_ref"])

    def test_over_threshold_truncates_and_keeps_full_blob(self):
        data = "".join(str(i % 10) for i in range(400))
        delivered, meta = prepare_stream(data, OPTS, self.blobs)

        self.assertTrue(meta["truncated"])
        self.assertEqual("head_tail", meta["strategy"])
        self.assertEqual(data[:10], delivered[:10])
        self.assertEqual(data[-10:], delivered[-10:])
        self.assertEqual(400, meta["bytes_total"])
        self.assertEqual(20, meta["head_bytes"] + meta["tail_bytes"])
        self.assertEqual(400 - 20, meta["elided_bytes"])

        blob = (self.blobs / meta["blob_ref"]).read_bytes()
        self.assertEqual(data.encode("utf-8"), blob)
        self.assertEqual(meta["sha256_full"],
                         hashlib.sha256(data.encode("utf-8")).hexdigest())

    def test_reconstruct_returns_exactly_what_agent_saw(self):
        data = "".join(str(i % 10) for i in range(400))
        delivered, meta = prepare_stream(data, OPTS, self.blobs)
        blob = (self.blobs / meta["blob_ref"]).read_bytes()

        self.assertEqual(delivered.encode("utf-8"), reconstruct(blob, meta))
        self.assertEqual(len(delivered.encode("utf-8")), meta["bytes_delivered"])
        self.assertEqual(meta["sha256_delivered"],
                         hashlib.sha256(delivered.encode("utf-8")).hexdigest())

    def test_multibyte_split_lands_on_character_boundary(self):
        # head/tail 按字符切分，所以切点不会落在多字节字符中间。
        data = "汉字测试" * 100
        delivered, meta = prepare_stream(data, OPTS, self.blobs)
        blob = (self.blobs / meta["blob_ref"]).read_bytes()

        self.assertEqual(data[:10], delivered[:10])
        self.assertEqual(data[-10:], delivered[-10:])
        self.assertEqual(delivered.encode("utf-8"), reconstruct(blob, meta))
        self.assertEqual(len(delivered.encode("utf-8")), meta["bytes_delivered"])

    def test_reconstruction_holds_across_many_sizes(self):
        for n in range(0, 500, 7):
            with self.subTest(chars=n):
                data = "".join(chr(0x4E00 + (i % 97)) for i in range(n))
                delivered, meta = prepare_stream(data, OPTS, self.blobs)
                blob = (data.encode("utf-8") if not meta["truncated"]
                        else (self.blobs / meta["blob_ref"]).read_bytes())
                self.assertEqual(delivered.encode("utf-8"), reconstruct(blob, meta))
                self.assertEqual(len(delivered.encode("utf-8")), meta["bytes_delivered"])


# 与生产配置一致的上限。OPTS 太小（阈值 100），字符数永远先于字节数触顶，
# 于是走不进"重叠区"——那里才是 bug 所在。
PROD_OPTS = TraceOptions(truncate_threshold_bytes=8192, head_chars=3000, tail_chars=3000)


class MultibyteOverlapTest(unittest.TestCase):
    """重叠区：字符数没超 head+tail，字节数却超了阈值。

    汉字 3 字节/字符，故 chars 在 (8192/3, 6000] 区间时同时满足
    "总字符 ≤ head+tail"和"总字节 > 阈值"。旧实现按字符切、不卡字节，
    head 与 tail 各取满 3000 字符 = 各 9000 字节，合计 18000 字节，
    比原文还长，elided_bytes 变成负数。
    """

    def setUp(self):
        self.blobs = self.enterContext(support.scratch_dir("blobs"))

    def test_truncation_never_delivers_more_than_it_received(self):
        for chars in (2731, 3000, 4000, 6000):
            with self.subTest(chars=chars):
                data = "".join(chr(0x4E00 + (i % 97)) for i in range(chars))
                delivered, meta = prepare_stream(data, PROD_OPTS, self.blobs)

                self.assertTrue(meta["truncated"], "该进重叠区却没被截断")
                self.assertGreater(meta["bytes_total"], PROD_OPTS.truncate_threshold_bytes)
                self.assertGreaterEqual(meta["elided_bytes"], 0)
                self.assertLessEqual(meta["bytes_delivered"], meta["bytes_total"])
                # "真的截掉了东西"：留在交付文本里的字节严格少于原文。
                self.assertLess(meta["head_bytes"] + meta["tail_bytes"], meta["bytes_total"])
                self.assertNotIn("truncated -", meta["marker_text"])

                blob = (self.blobs / meta["blob_ref"]).read_bytes()
                self.assertEqual(data.encode("utf-8"), blob)
                self.assertEqual(delivered.encode("utf-8"), reconstruct(blob, meta))
                self.assertEqual(len(delivered.encode("utf-8")), meta["bytes_delivered"])

    def test_the_delivered_text_is_shorter_than_the_original(self):
        # 上一条的直白版本：agent 拿到的确实比原文短。
        data = "汉字测试" * 1000
        delivered, meta = prepare_stream(data, PROD_OPTS, self.blobs)

        self.assertLess(meta["bytes_delivered"], meta["bytes_total"])
        # 省下来的字节 = 略去的正文 - 标记自身的字节。标记是观测工具加的
        # 开销，不算"省略的内容"，故 `elided_bytes` 不该含它。
        self.assertEqual(meta["bytes_total"] - meta["bytes_delivered"],
                         meta["elided_bytes"] - len(meta["marker_text"].encode("utf-8")))
