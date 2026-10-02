# rag/py/api.py —— 三件套后端:复用现有服务层,不改它们一行
#
# 与设计文档《RAG-前端三件套设计》的差异,只有静态文件这一段:
#   文档 §4/§5 假定前端放在 rag/web/,每条静态文件写一条路由;
#   实际前端在 rag/py/js_html_css/ 且有 index.html + data.html 两个页面,
#   所以这里改成 WEB_DIR 指向该目录、静态文件按文件名查表伺服(白名单,防目录穿越)。
#   §3 的 4 个 HTTP 契约与文档完全一致,前端一个字都不用改。
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

try:                      # 和你其他模块同款的双导入写法
    from . import file_histry as fh
    from .knowledge_base import KnowledgeBaseService
    from .rag import RagService
except ImportError:
    import file_histry as fh
    from knowledge_base import KnowledgeBaseService
    from rag import RagService

app = FastAPI(title="RAG 问答(三件套版)")

WEB_DIR = Path(__file__).resolve().parent.parent / "js_html_css"
ALLOWED_EXT = {"txt", "md", "csv"}

# 静态白名单:值 = media_type。只伺服这几样,其余一律 404,
# 顺带挡住 ../ 之类的目录穿越。
STATIC_FILES = {
    "index.html": "text/html",
    "data.html": "text/html",
    "app.css": "text/css",
    "app.js": "text/javascript",
}

# ★ 模块级单例:启动建一次。顺带修掉了 app_qa.py:35「每问一次重建 RagService」
#   的老问题(体检文档 §4 #2),单用户 MVP 下线程安全无虞;多用户是 Go 二期的事。
#   注意:RagService() 会读 os.environ["api_key_jev"] 并联网建 embeddings 客户端,
#   所以启动前必须先加载 rag/key.env(见本文件末尾 __main__ 的说明)。
kb = KnowledgeBaseService()
rag_service = RagService()


def _check_web_dir() -> None:
    """启动自检:前端目录/文件缺了就直接告警,别等用户点开页面才发现白屏。

    注意 html 里的资源引用是相对路径(./app.css),所以 4 条静态路由必须和
    页面路由处在同一层(都在根下),不能把静态文件挂到 /static 之类的子路径。
    """
    missing = [name for name in STATIC_FILES if not (WEB_DIR / name).is_file()]
    if missing:
        print(
            f"[api] 警告:前端文件缺失 {missing}\n"
            f"[api] 期望目录:{WEB_DIR}\n"
            f"[api] 页面会白屏/图标错位,请确认 js_html_css 这个目录的位置。"
        )


_check_web_dir()


def _static(name: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"前端文件缺失:{name}")
    return FileResponse(path, media_type=f"{STATIC_FILES[name]}; charset=utf-8")


def decode_text(raw: bytes) -> str:
    """从 app_file_uploader.py 原样搬来的编码链(中文 txt 大量是 GBK)。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


# ── 静态三件套:两个页面 + 两个资源 ──────────────────────────────
@app.get("/", include_in_schema=False)
def index():
    return _static("index.html")


@app.get("/data.html", include_in_schema=False)
def data_page():
    return _static("data.html")


@app.get("/app.css", include_in_schema=False)
def css():
    return _static("app.css")


@app.get("/app.js", include_in_schema=False)
def js():
    return _static("app.js")


# ── API ────────────────────────────────────────────────────────
@app.get("/api/new_session")
def new_session():
    return {"session_id": fh.new_session_id()}


@app.get("/api/history")
def history(session_id: str):
    msgs = fh.get_session_history(session_id).messages
    role_map = {"human": "user", "ai": "assistant"}
    return {"messages": [
        {"role": role_map.get(m.type, m.type), "message": m.content}
        for m in msgs
        if isinstance(m.content, str)      # 万一历史里混进多模态消息,别让整页 500
    ]}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXT:
        return JSONResponse(
            {"ok": False, "message": f"只支持 {'/'.join(sorted(ALLOWED_EXT))},收到 .{ext}"},
            status_code=400,
        )
    text = decode_text(await file.read())
    if not text.strip():
        return JSONResponse({"ok": False, "message": "文件内容为空,未入库。"}, status_code=400)
    msg = kb.update_by_str(text, file.filename)
    return {"ok": msg.startswith("ok"), "message": msg}


@app.post("/api/chat")
def chat(question: str = Form(...), session_id: str = Form(...)):
    def gen():
        try:
            for token in rag_service.chat(question, session_id):
                frame = {"type": "token", "text": token}
                yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"
            yield 'data: {"type": "done"}\n\n'
        except Exception as exc:                     # 兜底:页面不崩,toast 给人话
            frame = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # 直接 `python py/api.py` 也能起:先把 key.env 读进环境再 import(rag.py 需要 api_key_jev)。
    # 但用文档 §9 的 uvicorn 命令时,这一步要你自己先加载 key.env,见文末提示。
    import os
    from pathlib import Path as _Path

    env_file = _Path(__file__).resolve().parent.parent / "key.env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)
