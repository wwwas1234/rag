# cs/test_knowledge_base.py —— 入库/去重/僵尸清理 的离线测试
#
# 跑法(在 rag/ 目录下):
#   .venv\Scripts\python.exe -m unittest discover -s cs -v
#
# 测试原理(为什么敢随便跑,任何机器上都不会弄脏你的数据):
#   1. Chroma 用纯内存模式(persist_directory=None)——不落盘、无临时文件、无清理问题;
#      构造 KnowledgeBaseService 时把 Chroma 类 patch 掉,所以绝不碰真库 rag/data/chroma_db;
#   2. embedding 换成假向量(同一段文字永远同一个向量)—— 全程零网络请求;
#   3. 期望的段落数全部用同一个 splitter 现场算出来,不写死数字。
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

RAG_ROOT = Path(__file__).resolve().parent.parent
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from langchain_chroma import Chroma  # noqa: E402

from py import config  # noqa: E402
from py.knowledge_base import KnowledgeBaseService, get_string_md5  # noqa: E402


class FakeEmbeddings:
    """离线假向量:md5(文字) -> 固定向量。同样的文字永远同样的向量。"""

    def _vec(self, text: str, dim: int = 8):
        digest = get_string_md5(text).encode("utf-8")  # 32 个十六进制字符
        return [digest[i % len(digest)] / 255.0 for i in range(dim)]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def para(idx: int) -> str:
    """造一个约 480 字、内容唯一的段落(不超过 CHUNK_SIZE=500,不会被二次切)。"""
    return f"这是第{idx}号主题的专属段落。" + f"第{idx}号主题的正文内容。" * 36


class KnowledgeBaseTests(unittest.TestCase):
    FILE = "笔记.txt"

    def setUp(self):
        # 纯内存 Chroma:测试专用,绝不碰 rag/data/chroma_db,也不产生任何文件。
        # ★ 每个测试一个独立集合名:chromadb 的内存客户端在进程内是共享的,
        #   不隔离的话,前一个测试的 chunk 会漏进后一个测试的断言里。
        self.collection = f"t_{uuid.uuid4().hex[:8]}"
        fake_chroma = Chroma(
            persist_directory=None,
            collection_name=self.collection,
            embedding_function=FakeEmbeddings(),
        )
        # 把 knowledge_base 里的 Chroma 类换掉,KnowledgeBaseService() 构造时
        # 就拿不到真的 PersistentClient(它会去开 rag/data/chroma_db 的磁盘 sqlite)
        with patch("py.knowledge_base.Chroma", lambda **kwargs: fake_chroma):
            self.svc = KnowledgeBaseService()
        self.svc.chroma = fake_chroma

    # ── 小工具 ──────────────────────────────────────────────
    def split(self, text):
        return self.svc.splitter.split_text(text)

    def chunk_ids(self, text, file_name=FILE):
        """按 knowledge_base.update_by_str 的同款公式算出各段 id。"""
        return [f"{file_name}:{get_string_md5(c)[:16]}" for c in self.split(text)]

    def all_ids(self):
        return set(self.svc.chroma.get(include=[])["ids"])

    # ── 用例 ────────────────────────────────────────────────
    def test_first_upload(self):
        """第一次上传:全部段落入库,返回 ok。"""
        doc = "\n\n".join([para(1), para(2), para(3)])
        n = len(self.split(doc))
        self.assertGreaterEqual(n, 2, "测试文档构造有误,应当被切成多段")

        res = self.svc.update_by_str(doc, self.FILE)
        self.assertEqual(res, f"ok,已入库 {n} 段(跳过重复 0 段)")
        self.assertEqual(len(self.all_ids()), n)

    def test_reupload_same_content_rejected(self):
        """同一文件原样重传:应被拒('内容重复'),库不增长。"""
        doc = "\n\n".join([para(1), para(2), para(3)])
        self.svc.update_by_str(doc, self.FILE)
        before = len(self.all_ids())

        res = self.svc.update_by_str(doc, self.FILE)
        self.assertEqual(res, "不ok,内容重复(0 条新段落)")
        self.assertEqual(len(self.all_ids()), before)

    def test_metadata_has_source_key(self):
        """★ 回归守卫:每条 chunk 的 metadata 必须带 'source' 键。

        僵尸清理(update_by_str 里 where={"source": file_name})靠这个键工作。
        如果入库时写的键不是 source(比如写成了别的名字),
        僵尸清理会静默失效:不报错,但永远不删任何东西。
        """
        doc = "\n\n".join([para(1), para(2)])
        self.svc.update_by_str(doc, self.FILE)

        got = self.svc.chroma.get(include=["metadatas"])
        self.assertTrue(got["metadatas"], "库里查不到任何 chunk")
        for meta in got["metadatas"]:
            self.assertEqual(
                meta.get("source"), self.FILE,
                f"chunk metadata 缺 source 键(现在存的是 {meta})——"
                "僵尸清理的 where 过滤会永远查空,见体检文档 §4 #4",
            )

    def test_zombie_cleanup_on_modified_reupload(self):
        """★ 核心语义:同名文件'改一段+删一段'重传,旧段落必须被清掉。

        期望(设计语义):
          - 没改的段落:跳过(已在库)
          - 改过的段落:旧 id 被删、新 id 入库
          - 被删的段落:旧 id 被删(僵尸清理)
        最终库里应恰好只剩新版本的段落,一条旧尸都不留。
        """
        doc_v1 = "\n\n".join([para(1), para(2), para(3)])
        self.svc.update_by_str(doc_v1, self.FILE)

        doc_v2 = "\n\n".join([para(1), para(2) + "此处是被修改后的新内容。"])  # 删了第3段,改了第2段
        res = self.svc.update_by_str(doc_v2, self.FILE)

        ids_v2 = set(self.chunk_ids(doc_v2))
        ids_v1 = set(self.chunk_ids(doc_v1))
        self.assertTrue(ids_v2 & ids_v1, "构造有误:两版至少应有未改动的公共段落")
        self.assertTrue(ids_v1 - ids_v2, "构造有误:两版至少应有被改/删的段落")

        # 最终库 == 恰好新版本的段落集合
        self.assertEqual(self.all_ids(), ids_v2,
                         "库里留了旧版本的段落(僵尸)——检查僵尸清理是否真的生效")
        # 被删/被改的旧 id 确实不在库里
        for stale_id in ids_v1 - ids_v2:
            self.assertNotIn(stale_id, self.all_ids())
        # 返回信息里的"跳过"数 = 公共段落数
        self.assertIn(f"跳过重复 {len(ids_v2 & ids_v1)} 段", res)

    def test_empty_content_rejected(self):
        """空内容:直接回'内容为空',不碰库。"""
        res = self.svc.update_by_str("   \n\n  ", self.FILE)
        self.assertEqual(res, "不ok,内容为空")

    def test_same_paragraph_different_filename_is_new(self):
        """已知设计行为(不是 bug):id 里含文件名,
        所以同一段文字换个文件名传,会作为新 chunk 入库。
        这个测试把行为钉在这里,防止将来无意识改变。
        """
        doc_a = "\n\n".join([para(1), para(2)])
        self.svc.update_by_str(doc_a, "甲.txt")
        before = len(self.all_ids())

        self.svc.update_by_str(para(1), "乙.txt")   # 乙.txt 只有和甲.txt 一样的第1段
        self.assertEqual(len(self.all_ids()), before + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
