import streamlit as st

try:                      # 包内导入（推荐：python -m py.app_file_uploader）
    from .knowledge_base import KnowledgeBaseService
except ImportError:       # 兼容：cd py 后直接 streamlit run app_file_uploader.py
    from knowledge_base import KnowledgeBaseService
###########这里记得换成前端三件套
st.title("File Uploader")

# ★ 只声明真正支持的类型。原代码允许 pdf/xlsx，但下面是对字节流做文本解码，
#   二进制文件必然乱码或抛异常 —— 要么补解析器，要么先从这里去掉。
uploaded_file = st.file_uploader(
    "Upload a file", type=["txt", "md", "csv"], accept_multiple_files=False
)


def decode_text(raw: bytes) -> str:
    """按优先级尝试常见编码解码。

    中文 Windows 下的 txt/csv 大量是 GBK/GB18030，写死 utf-8 会直接抛
    UnicodeDecodeError。这里逐个尝试，最后用 latin-1 兜底（它不会失败）。
    """
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


if "service" not in st.session_state:
    st.session_state["service"] = KnowledgeBaseService()

if uploaded_file is not None:
    st.write("File uploaded successfully!")
    st.write("File name:", uploaded_file.name)
    st.write("File type:", uploaded_file.type)
    st.write("File size:", uploaded_file.size, "bytes")

    try:
        text = decode_text(uploaded_file.getvalue())
    except Exception as exc:                       # 兜底，避免 Streamlit 红屏
        st.error(f"文件解码失败：{exc}")
        st.stop()

    if not text.strip():
        st.warning("文件内容为空，未入库。")
        st.stop()

    with st.spinner("Processing file..."):
        result = st.session_state["service"].update_by_str(text, uploaded_file.name)
    st.write(result)
