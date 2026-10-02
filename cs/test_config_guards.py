# cs/test_config_guards.py —— config.py 的回归守卫测试
#
# 跑法(在 rag/ 目录下):
#   .venv\Scripts\python.exe -m unittest discover -s cs -v
# 只测 config.py,不发网络请求、不碰任何数据文件。
import sys
import unittest
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parent.parent   # -> rag/
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from py import config  # noqa: E402  (需要 rag 根目录在 sys.path 里)


class ConfigGuardTests(unittest.TestCase):
    """守卫这个项目里真实发生过/差点发生的问题,防止改回去。"""

    def test_base_url_jev_no_invisible_chars(self):
        """回归守卫:BASE_URL_JEV 默认值曾带零宽空格(U+200B)。
        那个字符肉眼不可见,却会让所有 Jev 请求 404。
        修法见 docx/JEV-调用指南-从TopK里挑有用的.md §2.1。
        """
        self.assertNotIn(
            "\u200b", config.BASE_URL_JEV,
            "BASE_URL_JEV 里混进了零宽空格!把 config.py 那一行重新手打一遍(别复制)",
        )

    def test_jev_model_pinned(self):
        """Jev 模型必须是钉死的版本号,不能是 latest。
        阈值是针对具体版本调的,latest 会随官方升级悄悄变。
        """
        self.assertTrue(config.JEV_MOD, "JEV_MOD 是空的")
        self.assertNotEqual(config.JEV_MOD, "jev-latest")

    def test_top_k_is_sane(self):
        """TOP_K 决定塞给 LLM 的候选条数,必须是正整数。"""
        self.assertIsInstance(config.TOP_K, int)
        self.assertGreater(config.TOP_K, 0)

    def test_keys_present(self):
        """三路 API key 都必须加载成功(缺任何一路,对应功能当场挂)。"""
        for name in ("EMB_API_KEY", "CHAT_API_KEY", "JEV_API_KEY"):
            self.assertTrue(
                getattr(config, name),
                f"config.{name} 是空的,检查 rag/key.env 里有没有对应的一行",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
