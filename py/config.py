import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "key.env")

EMB_API_KEY  = os.environ.get("api_key_emb")
CHAT_API_KEY = os.environ.get("api_key_chat")
JEV_API_KEY = os.environ.get("api_key_jev")


if not EMB_API_KEY or not CHAT_API_KEY:
    raise RuntimeError(
        f"缺少 API key。请检查 {Path(__file__).parent.parent / 'key.env'} "
        "里是否有 api_key_emb 和 api_key_chat 两行"
    )
BASE_URL_EMB  = os.environ.get("base_url_emb",  "https://api.siliconflow.cn/v1")
BASE_URL_CHAT = os.environ.get("base_url_chat", "https://opencode.ai/zen/go/v1")
BASE_URL_JEV = os.environ.get("base_url_jev", "https://openrouter.ai/api/v1/systemone")

EMB_MODEL    = os.environ.get("model_emb",  "BAAI/bge-m3")
CHAT_MODEL   = os.environ.get("model_chat", "deepseek-v4.1-flash")
JEV_MOD = os.environ.get("model_jev", "jev-1.13")

CHROMA_NAME  = "chroma"
CHROMA_DIR   = str(Path(__file__).parent.parent / "data" / "chroma_db")
COLLECTION   = "mvp0"
CHUNK_SIZE   = 500      
CHUNK_OVERLAP = 80
SEPARATORS   = ["\n\n", "\n",".","。","!","?"," ",""]
TOP_K        = 32

OPERATOR = "taffy"

APP_USER_AGENT = "cs-game-rag/1.0"

# ★ 必须用绝对路径：相对路径会随进程 CWD 漂移（从 py/ 启动和从仓库根启动
#   会解析到两个不同的文件），导致去重静默失效 -> 同一文档重复入库。
MD5_PATH = str(Path(__file__).parent.parent / "data" / "md5.txt")