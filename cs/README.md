# cs/ —— RAG 离线测试套件

**框架**:Python 标准库 `unittest`(零新依赖,venv 里没装 pytest 也能跑)。
**性质**:单元测试 —— 全程**离线**(零网络请求)、**不碰真数据**(绝不读写 `rag/data/`)。

## 怎么跑

```powershell
# 在 rag/ 目录下:
.venv\Scripts\python.exe -m unittest discover -s cs -v
```

只想跑一个文件(在 rag/ 目录下):

```powershell
.venv\Scripts\python.exe -m unittest cs.test_jev -v
.venv\Scripts\python.exe -m unittest cs.test_knowledge_base -v
.venv\Scripts\python.exe -m unittest cs.test_config_guards -v
```

## 三个文件各测什么

| 文件 | 测什么 | 怎么做到离线 |
|---|---|---|
| `test_config_guards.py` | config.py 的回归守卫:BASE_URL_JEV 无隐形字符、Jev 模型钉版本、TOP_K 合法、三路 key 已加载 | 纯读 config |
| `test_jev.py` | `rag.py` 的 `jev_pick_useful`:空库不发请求、阈值过滤+排序、top_n 截断、失败兜底、**发给 Jev 的请求形状**({id,text} 转换、400 字截断、真判据、模型钉版本) | 把 `py.rag.client` mock 掉,手工构造和真 API 同构的响应 |
| `test_knowledge_base.py` | `knowledge_base.py` 的 `update_by_str`:首次入库、重传被拒、空内容、**每条 chunk 必须带 `source` 键**、**僵尸清理**、跨文件名行为 | Chroma 用**纯内存模式** + 假向量;构造 `KnowledgeBaseService` 时把 Chroma 类 patch 掉,绕开真库 |

## 当前状态(2026-09 实测):15 个测试,13 过,2 失败

**两个失败都是同一个真 bug,一行就能修**:

`knowledge_base.py:102-104` 入库时 metadata 写的键是 `ids`:

```python
metadatas = {
    "ids": file_name     # ✗ 键名写错了
}
```

而僵尸清理(`knowledge_base.py:98`)按 `where={"source": file_name}` 过滤 —— 新段落根本没有 `source` 这个键,所以 **僵尸清理永远不会触发**(不报错,只是永远不干活)。

失败证据(测试输出的原文):

```
FAIL: test_metadata_has_source_key
AssertionError: None != '笔记.txt' : chunk metadata 缺 source 键(现在存的是 {'ids': '笔记.txt'})

FAIL: test_zombie_cleanup_on_modified_reupload
AssertionError: 库里留了旧版本的段落(僵尸)——检查僵尸清理是否真的生效
  (留下的正好是:被改段落的旧版本 + 被删段落,共 2 条)
```

**修法(一行)**:

```python
metadatas = {
    "source": file_name       # ✓ 和僵尸清理的 where={"source": ...} 对上
}
```

修完重跑,应该 **15/15 全绿**。建议顺手把 `created_at`/`operator` 两个审计字段也补回来(原版有),但 `source` 这一个键是必须的。

## 两个说明

1. 输出里那行 `[jev] 重排失败,本轮退回原始顺序: network down` 是**兜底测试故意模拟断网**打的日志,不是真出了网络问题;
2. Chroma 用内存模式(`persist_directory=None`)而不是临时目录:不落盘、无临时文件、无需清理,任何机器上跑完不留痕迹。代价是"跨进程持久化"不在这些测试范围内(那是 Chroma 自己的事,不是你代码的事)。

## 以后加测试

- 新文件命名 `test_*.py`,放本目录,顶部照抄现有文件的 `sys.path` 三行;
- 断言消息**写人话**(像上面那样把"缺什么、去哪修"写进消息),失败时未来的你不用考古。
