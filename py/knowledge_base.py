import os
import hashlib

try:                      # 包内导入（推荐：python -m py.app_file_uploader）
    from . import config
except ImportError:       # 兼容：cd py 后直接 streamlit run app_file_uploader.py
    import config
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from datetime import datetime

def check_md5(md5:str):
    if not os.path.exists(config.MD5_PATH):
        os.makedirs(os.path.dirname(config.MD5_PATH), exist_ok=True)
        with open(config.MD5_PATH,"w", encoding="utf-8"):
            pass
        return False
    with open(config.MD5_PATH,"r", encoding="utf-8") as f:
        return md5 in f.read().splitlines()


def save_md5(md5:str):
    os.makedirs(os.path.dirname(config.MD5_PATH), exist_ok=True)
    with open(config.MD5_PATH,"a", encoding="utf-8") as f:
        f.write(md5 + "\n")

def get_string_md5(input_string: str,ecoding='utf-8'):
    string_md5 = hashlib.md5(input_string.encode(ecoding)).hexdigest()
    return string_md5


class KnowledgeBaseService(object):
    def __init__(self):
        os.makedirs(config.CHROMA_DIR, exist_ok=True)
        self.chroma=Chroma(
            persist_directory=config.CHROMA_DIR,
            collection_name=config.COLLECTION,
            embedding_function=OpenAIEmbeddings(model=config.EMB_MODEL, api_key=config.EMB_API_KEY, base_url=config.BASE_URL_EMB)
        )

        self.splitter=RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            separators=config.SEPARATORS,
            length_function=len
        )

    # def update_by_str(self,data,file_name):
    #     md5_hex=get_string_md5(data)
    #     if check_md5(md5_hex):
    #         return "不ok,内容重复"

    #     # ★ 无条件切分。原代码用 `if len(data) > MAX_TOKENS(2000)` 做外层判断，
    #     #   但 len() 数的是「字符」而常量名写的是 token，两者不可比 ——
    #     #   结果是任何短于 2000 字符的文档整篇作为一个 chunk 入库（检索粒度=整篇）。
    #     #   splitter 自己会正确处理短文本，不需要外层判断。
    #     Know_chinks = self.splitter.split_text(data)
    #     if not Know_chinks:
    #         return "不ok,内容为空"

    #     metadatas = {
    #         "source": file_name,
    #         "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #         "operator": config.OPERATOR
    #     }

    #     # ★ 确定性 id：同一文档重传不会产生副本（原代码不传 ids，LangChain 会生成随机 UUID）
    #     ids = [
    #         f"{file_name}:{get_string_md5(chunk)[:16]}"
    #         for chunk in Know_chinks
    #     ]

    #     self.chroma.add_texts(
    #         Know_chinks,
    #         metadatas=[metadatas for _ in range(len(Know_chinks))],
    #         ids=ids,
    #     )

    #     save_md5(md5_hex)

    #     return f"ok,已入库 {len(Know_chinks)} 段"
    def update_by_str(self, data, file_name):
        Know_chinks = self.splitter.split_text(data)
        if not Know_chinks:
            return "不ok,内容为空"

        ids = [f"{file_name}:{get_string_md5(c)[:16]}" for c in Know_chinks]

        # ── chunk 级去重:只插库里还没有的,代替文件级 md5 门 ──
        got = self.chroma.get(ids=ids, include=[])          # 一次批量查
        existing = set(got["ids"])
        new_idx = [i for i, id_ in enumerate(ids) if id_ not in existing]
        if not new_idx:
            return "不ok,内容重复(0 条新段落)"             # 整篇全旧 = 等价于现在的"内容重复"

        # ── 僵尸清理:同名文件重传时,先删掉这次没有、上次有的 chunk ──
        old = set(self.chroma.get(where={"source": file_name}, include=[])["ids"])
        stale = old - set(ids)
        if stale:
            self.chroma.delete(ids=list(stale))              # 你删掉的段落不再被召回
        metadatas = {
            "source": file_name
        }
        self.chroma.add_texts(
            [Know_chinks[i] for i in new_idx],
            metadatas=[metadatas for _ in new_idx],
            ids=[ids[i] for i in new_idx],
        )
        return f"ok,已入库 {len(new_idx)} 段(跳过重复 {len(ids) - len(new_idx)} 段)"



