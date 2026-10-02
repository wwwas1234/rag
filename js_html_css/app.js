/* ==========================================================================
   RAG 前端三件套 —— 行为(设计文档 §7 行为清单 + 两界面版)
     问答页 body[data-page="qa"]   : 气泡、SSE 流式、历史恢复、新对话
     数据页 body[data-page="data"] : 上传入库、拖拽、结果条
   两个界面共用这一份 JS,按 body[data-page] 决定初始化哪一块。
   只依赖 fetch + FormData + ReadableStream,零外链(设计文档 §10)。
   ========================================================================== */
(function () {
  "use strict";

  var SESSION_KEY = "rag_session_id";
  /* 欢迎语与 app_qa.py 保持一致,好让 Streamlit 版和三件套版并排对照 */
  var WELCOME_TEXT = "你好，我是RAG问答系统，请问有什么可以帮您？";
  var STATUS_HIDE_MS = 3000;   /* §8:状态条 / toast 3 秒自动淡出 */
  var FADE_MS = 400;           /* 与 CSS transition 对齐 */
  var MAX_TOASTS = 4;
  var MAX_INPUT_HEIGHT = 160;

  var page = (document.body && document.body.getAttribute("data-page")) || "qa";

  function $(id) { return document.getElementById(id); }

  /* ── toast:两个界面共用 ───────────────────────────────────────── */
  function showToast(message, isError) {
    var layer = $("toast-layer");
    if (!layer) return;

    var node = document.createElement("div");
    node.className = "toast" + (isError === false ? "" : " is-err");
    node.textContent = String(message);

    layer.appendChild(node);
    while (layer.children.length > MAX_TOASTS) layer.removeChild(layer.firstChild);

    window.setTimeout(function () {
      node.classList.add("is-out");
      window.setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, FADE_MS);
    }, STATUS_HIDE_MS);
  }

  /* ── 会话:数据页只读 localStorage,不建会话 ───────────────────── */
  function paintSessionLabel(sessionId) {
    var label = $("session-label");
    if (!label) return;
    label.textContent = sessionId || "—";
    label.title = sessionId || "还没有会话";
  }

  function getSessionId(force) {
    if (!force) {
      var cached = localStorage.getItem(SESSION_KEY);
      if (cached) { paintSessionLabel(cached); return Promise.resolve(cached); }
    }

    return fetch("/api/new_session")
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (!data || typeof data.session_id !== "string" || !data.session_id) {
          throw new Error("响应里没有 session_id");
        }
        localStorage.setItem(SESSION_KEY, data.session_id);
        paintSessionLabel(data.session_id);
        return data.session_id;
      })
      .catch(function (err) {
        paintSessionLabel(null);
        showToast("创建会话失败：" + err.message + "（确认后端 api.py 已启动）");
        return null;
      });
  }

  /* ==========================================================================
     数据页
     ========================================================================== */
  function initDataPage() {
    var dropzone = $("dropzone");
    var fileInput = $("file-input");
    var statusBox = $("upload-status");
    var uploading = false;
    var statusTimer = 0;

    paintSessionLabel(localStorage.getItem(SESSION_KEY));

    function showStatus(message, kind) {
      window.clearTimeout(statusTimer);
      statusBox.classList.remove("is-ok", "is-err", "is-pending", "is-out");
      statusBox.classList.add(kind === "ok" ? "is-ok" : kind === "err" ? "is-err" : "is-pending");
      statusBox.textContent = String(message);
      statusBox.hidden = false;

      if (kind === "pending") return;   /* "上传中…" 由结果覆盖,不自动消失 */

      statusTimer = window.setTimeout(function () {
        statusBox.classList.add("is-out");
        statusTimer = window.setTimeout(function () {
          statusBox.hidden = true;
          statusBox.classList.remove("is-out");
        }, FADE_MS);
      }, STATUS_HIDE_MS);
    }

    /* 类型/编码/去重全部由后端判定,前端只负责把 message 原样摆出来(§3.2) */
    function upload(file) {
      if (uploading) {
        showToast("上一个文件还在上传中，请稍候。", false);
        return;
      }
      uploading = true;
      dropzone.classList.add("is-busy");
      showStatus("上传中…", "pending");

      var fd = new FormData();
      fd.append("file", file);

      fetch("/api/upload", { method: "POST", body: fd })
        .then(function (resp) {
          return resp.json().catch(function () { return null; }).then(function (data) {
            if (data && typeof data.message === "string" && data.message) {
              showStatus(data.message, data.ok ? "ok" : "err");
            } else {
              showStatus("上传失败：HTTP " + resp.status, "err");
            }
          });
        })
        .catch(function (err) {
          showStatus("上传失败：" + err.message, "err");
        })
        .then(function () {
          uploading = false;
          dropzone.classList.remove("is-busy");
          fileInput.value = "";   /* 清空,同一个文件还能再传一次(验收第 3 条) */
        });
    }

    fileInput.addEventListener("change", function (e) {
      var file = e.target.files && e.target.files[0];
      if (file) upload(file);
    });

    /* label 自带点击转发到 input,这里只补键盘可达性 */
    dropzone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });

    /* 拖拽入库 */
    ["dragenter", "dragover"].forEach(function (type) {
      dropzone.addEventListener(type, function (e) {
        e.preventDefault();
        if (!uploading) dropzone.classList.add("is-dragover");
      });
    });

    ["dragleave", "dragend"].forEach(function (type) {
      dropzone.addEventListener(type, function () {
        dropzone.classList.remove("is-dragover");
      });
    });

    dropzone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropzone.classList.remove("is-dragover");
      var files = e.dataTransfer && e.dataTransfer.files;
      if (!files || !files.length) return;
      if (files.length > 1) showToast("一次只处理一个文件，已上传第一个。", false);
      upload(files[0]);
    });

    /* 别让文件被拖到页面其他位置时,浏览器直接把文件打开 */
    ["dragover", "drop"].forEach(function (type) {
      window.addEventListener(type, function (e) { e.preventDefault(); });
    });
  }

  /* ==========================================================================
     问答页
     ========================================================================== */
  function initQaPage() {
    var chatArea = $("chat-area");
    var input = $("question-input");
    var sendBtn = $("send-btn");
    var newChatBtn = $("new-chat-btn");

    var streaming = false;   /* 流式回答进行中 */
    var liveBubble = null;   /* 当前流式气泡:{ row, textEl, cursorEl } */

    /* 滚动:始终贴底,但用户往上翻历史时不抢滚动条 */
    function scrollToBottom(force) {
      var nearBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 120;
      if (force || nearBottom) chatArea.scrollTop = chatArea.scrollHeight;
    }

    function addBubble(role, text) {
      var row = document.createElement("div");
      row.className = "msg " + role;

      var bubble = document.createElement("div");
      bubble.className = "bubble " + role;

      var textEl = document.createElement("span");
      textEl.className = "bubble-text";
      textEl.textContent = text == null ? "" : String(text);   /* 纯文本,不解析 HTML */

      bubble.appendChild(textEl);
      row.appendChild(bubble);
      chatArea.appendChild(row);
      scrollToBottom(role === "user");
      return { row: row, bubble: bubble, textEl: textEl };
    }

    function startLiveBubble() {
      var b = addBubble("assistant", "");
      var cursor = document.createElement("span");
      cursor.className = "cursor";
      cursor.setAttribute("aria-hidden", "true");
      cursor.textContent = "▍";
      b.bubble.appendChild(cursor);
      liveBubble = { row: b.row, textEl: b.textEl, cursorEl: cursor };
      return liveBubble;
    }

    function appendToken(text) {
      if (!liveBubble) startLiveBubble();
      liveBubble.textEl.textContent += String(text == null ? "" : text);
      scrollToBottom();
    }

    function finishBubble() {
      if (!liveBubble) return;
      if (liveBubble.cursorEl.parentNode) {
        liveBubble.cursorEl.parentNode.removeChild(liveBubble.cursorEl);
      }
      /* 一个字都没收到(建会话失败/直接报错)时别留个空气泡 */
      if (!liveBubble.textEl.textContent && liveBubble.row.parentNode) {
        liveBubble.row.parentNode.removeChild(liveBubble.row);
      }
      liveBubble = null;
    }

    function showWelcome() {
      addBubble("assistant", WELCOME_TEXT);
      scrollToBottom(true);
    }

    function setBusy(busy) {
      streaming = busy;
      sendBtn.disabled = busy;
      sendBtn.textContent = busy ? "生成中…" : "发送";
    }

    /* ── 核心难点:SSE 流式读取 ─────────────────────────────────────
       EventSource 只支持 GET,POST 的流要用 fetch + ReadableStream 手读。 */
    function handleFrame(frame) {
      var parts = [];
      var lines = frame.split("\n");
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (line.charAt(0) === ":") continue;          /* 注释/心跳 */
        if (line.indexOf("data:") !== 0) continue;
        parts.push(line.slice(5).replace(/^ /, ""));
      }
      if (!parts.length) return null;

      var evt;
      try {
        evt = JSON.parse(parts.join("\n"));
      } catch (err) {
        return null;                                   /* 坏帧丢掉,别崩 */
      }
      if (!evt || typeof evt !== "object") return null;

      if (evt.type === "token") {
        appendToken(evt.text);
        return null;
      }
      if (evt.type === "done") {
        finishBubble();
        return "done";
      }
      if (evt.type === "error") {
        showToast(evt.message || "服务端返回了错误");
        finishBubble();
        return "error";
      }
      return null;
    }

    function ask(question) {
      return getSessionId()
        .then(function (sessionId) {
          if (!sessionId) return null;

          var fd = new FormData();
          fd.append("question", question);
          fd.append("session_id", sessionId);

          return fetch("/api/chat", { method: "POST", body: fd }).catch(function (err) {
            showToast("请求失败：" + err.message);
            return null;
          });
        })
        .then(function (resp) {
          if (!resp) return;

          /* §3.5:流式端点约定一律 200 + error 事件;这里兜住 4xx/5xx */
          if (!resp.ok) {
            return resp.json().catch(function () { return null; }).then(function (data) {
              var msg = data && data.message ? data.message : "HTTP " + resp.status;
              showToast("请求失败：" + msg);
            });
          }
          if (!resp.body) {
            showToast("当前浏览器不支持流式读取，请换新版浏览器。");
            return;
          }

          var reader = resp.body.getReader();
          var decoder = new TextDecoder("utf-8");
          var buf = "";
          var settled = false;   /* 收到 done 或 error 就算正常收尾 */

          function drain() {
            var idx;
            while ((idx = buf.indexOf("\n\n")) >= 0) {    /* SSE 一帧以空行分隔 */
              var frame = buf.slice(0, idx);
              buf = buf.slice(idx + 2);
              if (handleFrame(frame)) settled = true;
            }
          }

          function pump() {
            return reader.read().then(function (res) {
              if (res.done) return;
              buf += decoder.decode(res.value, { stream: true });
              buf = buf.replace(/\r\n/g, "\n");
              drain();
              return pump();
            });
          }

          return pump()
            .then(function () {
              buf += decoder.decode();                   /* 冲刷解码器尾部 */
              buf = buf.replace(/\r\n/g, "\n");
              if (buf.replace(/\s/g, "")) {
                if (handleFrame(buf)) settled = true;
              }
            })
            .catch(function (err) {
              showToast("读取响应中断：" + err.message);
            })
            .then(function () {
              finishBubble();
              if (!settled) showToast("连接提前结束，回答可能不完整。");
            });
        });
    }

    function send() {
      if (streaming) return;
      var question = input.value.trim();
      if (!question) { input.focus(); return; }

      addBubble("user", question);
      input.value = "";
      autoGrow();
      setBusy(true);
      startLiveBubble();          /* 先亮光标,首 token 到了再往里拼 */

      ask(question).then(function () {
        finishBubble();
        setBusy(false);
        input.focus();
      }, function (err) {
        showToast("发送失败：" + err.message);
        finishBubble();
        setBusy(false);
      });
    }

    /* 历史恢复:刷新不丢 */
    function loadHistory() {
      return getSessionId().then(function (sessionId) {
        if (!sessionId) { showWelcome(); return; }   /* 后端没起来也别给空白页 */

        return fetch("/api/history?session_id=" + encodeURIComponent(sessionId))
          .then(function (resp) {
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            return resp.json();
          })
          .then(function (data) {
            var messages = data && Array.isArray(data.messages) ? data.messages : [];
            if (!messages.length) { showWelcome(); return; }

            for (var i = 0; i < messages.length; i++) {
              var m = messages[i] || {};
              addBubble(m.role === "user" ? "user" : "assistant", m.message);
            }
            scrollToBottom(true);
          })
          .catch(function (err) {
            showToast("历史加载失败：" + err.message);
          });
      });
    }

    /* 新对话:清 localStorage + 清聊天区 + 重新拿 session_id */
    function newChat() {
      if (streaming) {
        showToast("正在生成回答，请稍候再试。", false);
        return;
      }
      localStorage.removeItem(SESSION_KEY);
      chatArea.replaceChildren();
      getSessionId(true).then(function (sessionId) {
        if (sessionId) showWelcome();
      });
    }

    /* 输入框自适应增高 */
    function autoGrow() {
      input.style.height = "auto";
      var next = Math.min(input.scrollHeight, MAX_INPUT_HEIGHT);
      input.style.height = next + "px";
      input.style.overflowY = input.scrollHeight > MAX_INPUT_HEIGHT ? "auto" : "hidden";
    }

    sendBtn.addEventListener("click", send);
    input.addEventListener("input", autoGrow);
    input.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.shiftKey) return;      /* Shift+Enter 换行 */
      if (e.isComposing || e.keyCode === 229) return;   /* 中文输入法组词中,不算发送 */
      e.preventDefault();
      send();
    });
    newChatBtn.addEventListener("click", newChat);

    autoGrow();
    loadHistory();
  }

  /* ── 按页面分发 ───────────────────────────────────────────────── */
  if (page === "data") initDataPage();
  else initQaPage();
})();
