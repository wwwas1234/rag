import streamlit as st

try:                      # 包内导入（推荐：python -m streamlit run py/app_qa.py）
    from . import file_histry as fh
    from .rag import RagService
except ImportError:       # 兼容：cd py 后直接 streamlit run app_qa.py
    import file_histry as fh
    from rag import RagService

st.title("RAG问答系统")
st.divider()

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "你好，我是RAG问答系统，请问有什么可以帮您？"}]

prompt=st.chat_input("请输入问题")

if "session_id" not in st.session_state:
    st.session_state.session_id = fh.new_session_id()
session_id = st.session_state.session_id


for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    else:
        st.chat_message("assistant").write(msg["content"])

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})
    ai_res=[]
    with st.chat_message("assistant"):
        st.info("正在生成回答，请稍等...")
        rag_service = RagService()
        def cap(gen,cache):
            for token in gen:
                cache.append(token)
                yield token
        response = rag_service.chat(prompt,session_id=session_id)
        st.chat_message("assistant").write_stream(cap(response,ai_res))

    st.session_state["messages"].append({"role": "assistant", "content": "".join(ai_res)})