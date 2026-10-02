from langchain_chroma import Chroma

try:                      # 包内导入（推荐：python -m py.app_qa）
    from . import config
except ImportError:       # 兼容：cd py 后直接 streamlit run app_qa.py
    import config


class VectorStore(object):
    def __init__(self, embedding):
        self.embedding = embedding
        self.vector_store = Chroma(
            collection_name=config.COLLECTION,
            embedding_function=self.embedding,
            persist_directory=config.CHROMA_DIR
        )

    def get_vector_store(self):
        return self.vector_store.as_retriever(search_kwargs={"k": config.TOP_K})####TOP_k记得改回32

if __name__ == "__main__":
    pass
