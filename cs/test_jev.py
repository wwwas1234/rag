# cs/test_jev.py —— jev_pick_useful 的离线测试(mock 掉网络)
#
# 跑法(在 rag/ 目录下):
#   .venv\Scripts\python.exe -m unittest discover -s cs -v
#
# 测试原理:py.rag 里的 client 被 mock 换成假对象,
# system_one 返回我们手工构造的 SystemOneResponse —— 全程零网络请求,
# 只验证"拿到概率之后怎么挑"这段纯逻辑(阈值/排序/截断/兜底/请求形状)。
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAG_ROOT = Path(__file__).resolve().parent.parent
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from langchain_core.documents import Document  # noqa: E402
from typesafe_sdk import NoulAnswer, SystemOneResponse, Usage  # noqa: E402

from py import rag  # noqa: E402  (import 时读 key.env、建 client,均不发网络请求)


def make_docs(n=3, text_len=60):
    return [
        Document(page_content=f"候选段落{i}:" + "正文内容" * text_len,
                 metadata={"source": f"f{i}.txt"})
        for i in range(n)
    ]


def fake_resp(probs: dict) -> SystemOneResponse:
    """手工构造一个和真 API 同构的响应:{"p0": 0.9, ...} -> answers。"""
    return SystemOneResponse(
        model="typesafe/jev-1.13-20260917",
        usage=Usage(input_tokens=100, output_tokens=10),
        answers={k: NoulAnswer(noul=v) for k, v in probs.items()},
    )


class JevPickUsefulTests(unittest.TestCase):

    def test_empty_docs_no_request(self):
        """空库/检索 0 条:直接返回 ([], []),绝不能发请求。
        (SDK 对空 questions 会直接抛错,所以这层保护必须有。)
        """
        with patch.object(rag, "client") as mock_client:
            kept, scored = rag.jev_pick_useful("问题", [])
        self.assertEqual(kept, [])
        self.assertEqual(scored, [])
        mock_client.system_one.assert_not_called()

    def test_threshold_and_order(self):
        """阈值 0.5:0.9 和 0.6 留下、0.2 扔掉;留下的按概率从高到低排。"""
        docs = make_docs(3)
        with patch.object(rag, "client") as mock_client:
            mock_client.system_one.return_value = fake_resp(
                {"p0": 0.2, "p1": 0.9, "p2": 0.6}
            )
            kept, scored = rag.jev_pick_useful("问题", docs)

        self.assertEqual([d.metadata["source"] for d in kept], ["f1.txt", "f2.txt"])
        self.assertEqual(scored, [(1, 0.9), (2, 0.6), (0, 0.2)])
        for d in kept:
            self.assertIsInstance(d, Document)   # f_d 拿到的是 Document,不是别的

    def test_top_n_truncation(self):
        """全部高概率时,最多只留 top_n 条,防止把上下文撑爆。"""
        docs = make_docs(3)
        with patch.object(rag, "client") as mock_client:
            mock_client.system_one.return_value = fake_resp(
                {"p0": 0.9, "p1": 0.95, "p2": 0.85}
            )
            kept, scored = rag.jev_pick_useful("问题", docs, top_n=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(scored), 3)          # scored 始终是全量,方便落日志

    def test_fallback_on_error(self):
        """网络/欠费/超时:不崩,退回原始顺序前 top_n 条(问答不中断)。"""
        docs = make_docs(3)
        with patch.object(rag, "client") as mock_client:
            mock_client.system_one.side_effect = RuntimeError("network down")
            kept, scored = rag.jev_pick_useful("问题", docs)
        self.assertEqual(kept, docs[:6])
        self.assertEqual(scored, [])

    def test_request_shape(self):
        """发给 Jev 的请求形状:passages 必须是 {id, text}、text 截断、
        判据必须是真判据(不能是省略号占位符)、model 钉版本。
        """
        long_doc = Document(page_content="很长的段落。" * 300)   # 2100 字
        with patch.object(rag, "client") as mock_client:
            mock_client.system_one.return_value = fake_resp({"p0": 0.9})
            rag.jev_pick_useful("问题", [long_doc], preview_chars=400)

        kwargs = mock_client.system_one.call_args.kwargs
        self.assertEqual(kwargs["model"], "jev-1.13")

        state = kwargs["state"]
        self.assertEqual(state["question"], "问题")
        p0 = state["passages"][0]
        self.assertEqual(set(p0.keys()), {"id", "text"}, 
                         "passages 必须转成 {id, text},不能是 Document 原样")
        self.assertLessEqual(len(p0["text"]), 400, "发给 Jev 的文本必须截断,防撞 32k 上下文")

        q0 = kwargs["questions"]["p0"]
        self.assertIn("untrusted data", q0.instructions)   # 提示注入缓解必须在
        self.assertEqual(q0.criteria["true"], rag.CRITERIA["true"])
        self.assertEqual(q0.criteria["false"], rag.CRITERIA["false"])
        self.assertNotEqual(q0.criteria["true"], "…", "判据不能是省略号占位符")


if __name__ == "__main__":
    unittest.main(verbosity=2)
