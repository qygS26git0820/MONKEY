"""截断的核心性质：交付给 agent 的文本必须能由 blob + 元数据逐字节重建。

这条性质的意义不是"内部实现正确"，而是"事后能还原 agent 当时看到的输入"。
只要它成立，观察者就不会被观测工具自身的截断引入偏差。
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
