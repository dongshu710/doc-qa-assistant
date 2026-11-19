"""会话存储：把「和文档的问答记录」从浏览器搬到项目的存储区。

为什么必须搬：
1. 换浏览器/换端口/清缓存就全没了——用户以为丢了资料，其实是从没存过；
2. 会话本身也是「文档记忆」的一部分：它记着当时依据了哪份文档、哪句引用，
   放在 localStorage 里，智能体永远读不到；
3. 文件要能自由修改，就不能是浏览器里的一坨 JSON。

目录约定（与笔记同一个 home，用户可以整目录搬走）：

    <home>/threads/<id>.json    一条会话一个文件，缩进过的 JSON，手改也能读

取舍：
- 一个会话一个文件，而不是一个大的 threads.json：并发写互不影响，用户也能单删。
- 整条 upsert（PUT）而不是增量 PATCH：单机单用户，前端本来就有完整对象，
  全量写反而没有「合并冲突」这种要解释的中间态；文件体积也就几十 KB。
- 不在服务端裁剪历史：删掉用户的东西比留一堆文件更糟。列表只返回最近 60 条。
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from . import atomicfile
from .timeutil import utc_now_iso

ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
MAX_TURNS = 500
MAX_BYTES = 4 * 1024 * 1024
# 元数据索引：`_index.json` 存 id → 标题/时间/sid/轮数，避免每次列表都把所有会话
# 正文读一遍。实测 300 条会话（13.9 MB）全扫要 4.2 秒，而这些信息只有几百字节。
# 放在 threads/ 下、名字以 `_` 开头：`.json` 的 glob 会扫到它，所有扫描都要显式排除。
INDEX_NAME = "_index.json"

# 索引里存多少搜索文本。侧栏的搜索原来只匹配标题，而标题是自动截的（前 28 字），
# 「我问过起购金额的事」这类回忆起点的词多半搜不到。问句全存、答案只取开头一小段：
# 答案长且冗余，整段塞进索引会把 300 条会话的索引从几十 KB 撑到几 MB。
SEARCH_TEXT_MAX = 600
SEARCH_SNIPPET = 60
# 索引格式版本。加字段就升一位：`_load_index` 见到旧版本直接当没有，
# 触发一次全量重建（300 条约 700ms，只发生一次），比写迁移代码可靠。
INDEX_SCHEMA = "thread-index/v2"


def _search_text(turns: list) -> str:
    """把一条会话压成可搜索的一行字。

    只收问句 + 答案开头：用户找旧对话时想起的是「我当时怎么问的」，
    而不是模型当时怎么答的；答案只用来兜住「答案里唯一的那个数字」。
    """
    parts: list[str] = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        question = str(item.get("q") or "").strip()
        if question:
            parts.append(question)
        # 答案在 `d.answer` 里：`_clean_turns` 只放行 q / ts / d，前端 slimTurn
        # 也把答案放在 d 下面。顶层 `a` 是测试/导出的写法，留作兜底。
        answer = ""
        if isinstance(item.get("d"), dict):
            answer = str(item["d"].get("answer") or "")
        if not answer:
            answer = str(item.get("a") or item.get("answer") or "")
        answer = answer.strip()
        if answer:
            parts.append(answer[:SEARCH_SNIPPET])
    return " ".join(parts)[:SEARCH_TEXT_MAX]

# 所有会话写入串行化。两个原因：
# 1) 每次请求都会 new 一个 ThreadStore，实例锁拦不住并发，必须是模块级的；
# 2) Windows 上两个线程同时 os.replace 到同一目标会抛 WinError 5（共享冲突），
#    先到的那个成功、后到的直接 500，而用户只是想保存一次对话。
_WRITE_LOCK = threading.Lock()

LIST_LIMIT = 60


class ThreadError(ValueError):
    """调用方把参数写错了（不是磁盘问题），映射成 400。"""


def _now() -> str:
    # 口径统一在 timeutil：三份相同实现分散在三个模块，改一处漏两处就是时区 bug
    return utc_now_iso()


class ThreadStore:
    def __init__(self, home: str | Path):
        self.home = Path(home).expanduser().resolve()
        self.dir = self.home / "threads"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- 元数据索引 ----
    #
    # 为什么要有它：`list()` 与 `queries_for_sid()` 原来都要把 threads/ 下每个
    # `.json` 完整 `json.load()` 一遍。实测 300 条会话（13.9 MB）时列表 763ms、
    # 追问回填 4249ms——而用户点开一条旧对话后第一次提问就要吃这个延迟。
    # 索引只需要 id/标题/时间/sid/轮数，几百字节。

    def _index_path(self) -> Path:
        return self.dir / INDEX_NAME

    def _load_index(self) -> dict | None:
        try:
            raw = self._index_path().read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return None
        # 版本不符就当没有：让 _index() 走一次全量重建。旧索引缺 `text` 字段时
        # 搜索会静默搜不到正文——「没报错但结果不对」比慢一次更难发现。
        if data.get("schema") != INDEX_SCHEMA:
            return None
        return data

    def _save_index(self, items: dict, count: int) -> None:
        atomicfile.write_json(str(self._index_path()),
                              {"schema": INDEX_SCHEMA, "count": count, "items": items})

    def _entry_of(self, thread_id: str, record: dict) -> dict:
        turns = record.get("turns") if isinstance(record.get("turns"), list) else []
        return {
            "title": str(record.get("title") or "新对话")[:120],
            "created": str(record.get("created") or ""),
            "updated": str(record.get("updated") or record.get("created") or ""),
            "sid": str(record.get("sid") or ""),
            "turns": len(turns),
            # 搜索用的一行字。放在索引里而不是搜索时读文件：300 条会话全读
            # 要 700ms+，而侧栏搜索是逐字实时过滤的。
            "text": _search_text(turns),
        }

    def _count_files(self) -> int:
        """目录里有多少个会话文件（不含索引本身）。

        只 `scandir` 不读内容：300 条约 1ms。用它跟索引里的 count 对账——
        用户手工删了文件、别的进程写了新会话，都能被这条廉价检查发现。
        """
        total = 0
        try:
            for entry in os.scandir(self.dir):
                if entry.name.endswith(".json") and not entry.name.startswith("_"):
                    total += 1
        except OSError:
            return 0
        return total

    def _rebuild_index(self) -> dict:
        """全量扫一遍重建索引；坏文件跳过但计入 count（否则每次都对不上、反复重建）。"""
        items: dict[str, dict] = {}
        count = 0
        try:
            entries = list(os.scandir(self.dir))
        except OSError:
            return {"count": 0, "items": {}}
        for entry in entries:
            if not entry.name.endswith(".json") or entry.name.startswith("_"):
                continue
            count += 1
            try:
                with open(entry.path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue      # 坏文件不该让整个列表消失
            if isinstance(data, dict):
                items[entry.name[:-5]] = self._entry_of(entry.name[:-5], data)
        self._save_index(items, count)
        return {"count": count, "items": items}

    def _index(self) -> dict:
        """取索引；与磁盘文件数对不上就重建。"""
        index = self._load_index()
        if index is not None and index.get("count") == self._count_files():
            return index
        return self._rebuild_index()

    def _index_touch(self, thread_id: str, record: dict, *, created_new: bool) -> None:
        """写入/删除后同步索引。索引不存在时不建——留给下次 `_index()` 全量重建，
        否则会写出一份只含一条记录、count 却是 0 的假索引。"""
        index = self._load_index()
        if index is None:
            return
        index["items"][thread_id] = self._entry_of(thread_id, record)
        if created_new:
            index["count"] = int(index.get("count") or 0) + 1
        self._save_index(index["items"], int(index.get("count") or 0))

    def _index_drop(self, thread_id: str) -> None:
        index = self._load_index()
        if index is None:
            return
        if index["items"].pop(thread_id, None) is not None:
            index["count"] = max(0, int(index.get("count") or 0) - 1)
        self._save_index(index["items"], int(index.get("count") or 0))

    # ---- 路径与校验 ----

    def path_for(self, thread_id: str) -> Path:
        if not ID_RE.match(str(thread_id or "")):
            raise ThreadError("会话 id 只能由 6~40 位字母、数字、下划线或短横线组成")
        return self.dir / f"{thread_id}.json"

    def _clean_turns(self, turns) -> list:
        if turns is None:
            return []
        if not isinstance(turns, list):
            raise ThreadError("turns 必须是数组")
        if len(turns) > MAX_TURNS:
            raise ThreadError(f"单条会话最多 {MAX_TURNS} 轮，更长的请拆成多条或存成笔记")
        out = []
        for item in turns:
            if not isinstance(item, dict):
                continue
            # 只保留已知字段：前端传来的 d 里东西很多，白名单能防止越存越大
            turn = {"q": str(item.get("q") or "")[:2000], "ts": str(item.get("ts") or "")[:40]}
            if isinstance(item.get("d"), dict):
                turn["d"] = item["d"]
            out.append(turn)
        return out

    # ---- 读 ----

    def get(self, thread_id: str) -> dict:
        path = self.path_for(thread_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise KeyError(thread_id) from None
        except OSError as exc:
            raise OSError(f"读取会话失败：{exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 手改坏了不能整页 500：当作「这篇读不出来」，把行号带回去
            raise ThreadError(f"会话文件不是合法 JSON（{path.name} 第 {exc.lineno} 行）") from None
        if not isinstance(data, dict):
            raise ThreadError(f"会话文件顶层必须是对象（{path.name}）")
        return self._shape(data, thread_id)

    def _shape(self, data: dict, thread_id: str) -> dict:
        turns = data.get("turns")
        return {
            "id": thread_id,
            "title": str(data.get("title") or "新对话")[:120],
            "created": str(data.get("created") or ""),
            "updated": str(data.get("updated") or data.get("created") or ""),
            "sid": str(data.get("sid") or ""),
            "turns": turns if isinstance(turns, list) else [],
        }

    def list(self, limit: int = LIST_LIMIT) -> list:
        """列表只给元数据，不带正文：侧栏要快，正文按需取。

        走 `_index.json`：300 条会话时原来要 763ms（每个文件完整 json.load），
        现在是个位数毫秒。索引与磁盘文件数对不上就自动重建——用户手删文件、
        别的进程写入新会话都能兜住，代价只是一次全扫。
        """
        index = self._index()
        items = [dict(entry, id=thread_id, mtime=0.0)
                 for thread_id, entry in index["items"].items()]
        items.sort(key=lambda item: (item.get("updated") or "", item["id"]), reverse=True)
        return items[:max(1, int(limit))]

    # ---- 写 ----

    def queries_for_sid(self, sid: str, limit: int = 6) -> list[str]:
        """按会话 id 找最近的一条对话，取最后几轮的「问句」。

        只取 `q`，不取答案：追问改写需要的是「上一轮问的什么」，
        把答案塞进上下文反而会把改写往上一轮的主题上带偏。
        取 updated 最大的那条：同一个 sid 理论上只属于一条对话，
        但用户可能从浏览器旧数据导入过重复的，取最新的是最不坏的选择。
        """
        sid = str(sid or "").strip()
        if not sid:
            return []
        # 先问索引「哪个会话属于这个 sid、哪个最新」，再只读那一份文件。
        # 原来是把目录里每个文件完整读一遍再比 sid：300 条会话实测 4249ms，
        # 而用户点开一条旧对话后第一次提问就要等这么久。
        index = self._index()
        candidates = [(entry.get("updated") or "", thread_id)
                      for thread_id, entry in index["items"].items()
                      if entry.get("sid") == sid]
        if not candidates:
            return []
        thread_id = max(candidates)[1]
        try:
            data = json.loads((self.dir / f"{thread_id}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []      # 坏文件不该让追问上下文整体失效
        if not isinstance(data, dict):
            return []
        turns = data.get("turns")
        if not isinstance(turns, list):
            return []
        questions = []
        for item in turns:
            if isinstance(item, dict):
                text = str(item.get("q") or "").strip()
                if text:
                    questions.append(text)
        return questions[-max(1, int(limit)):]

    def put(self, thread_id: str, data: dict) -> dict:
        path = self.path_for(thread_id)
        if not isinstance(data, dict):
            raise ThreadError("请求体必须是对象")
        turns = self._clean_turns(data.get("turns"))
        with _WRITE_LOCK:
            # 「文件是否已存在」要在锁内判断：两个并发 PUT 都以为自己是新建，
            # 索引的 count 就会多加一次，之后每次列表都对不上、反复重建。
            existed = path.exists()
            existing = {}
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            created = str(data.get("created")
                          or (existing.get("created") if isinstance(existing, dict) else "")
                          or _now())
            record = {
                "schema": "thread/v1",
                "id": thread_id,
                "title": str(data.get("title") or "新对话")[:120],
                "created": created,
                "updated": _now(),
                "sid": str(data.get("sid") or "")[:80],
                "turns": turns,
            }
            payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
            if len(payload.encode("utf-8")) > MAX_BYTES:
                raise ThreadError("这条会话太大了（超过 4 MB），建议把结论存成笔记")
            atomicfile.write_bytes(str(path), payload.encode("utf-8"))
            self._index_touch(thread_id, record, created_new=not existed)
        return {key: value for key, value in record.items() if key != "turns"} | {"turns": len(turns)}

    def delete(self, thread_id: str) -> None:
        path = self.path_for(thread_id)
        with _WRITE_LOCK:
            try:
                path.unlink()
            except FileNotFoundError:
                raise KeyError(thread_id) from None
            except OSError as exc:
                raise OSError(f"删除会话失败：{exc}") from exc
            self._index_drop(thread_id)

    def import_many(self, rows) -> int:
        """把浏览器里遗留的会话一次性搬进来；id 冲突就跳过，绝不覆盖磁盘上的。"""
        if not isinstance(rows, list):
            raise ThreadError("threads 必须是数组")
        copied = 0
        for row in rows[:200]:
            if not isinstance(row, dict):
                continue
            thread_id = str(row.get("id") or "")
            if not ID_RE.match(thread_id):
                continue
            target = self.dir / f"{thread_id}.json"
            if target.exists():
                continue
            try:
                self.put(thread_id, row)
                copied += 1
            except (ThreadError, OSError):
                continue
        return copied

    def size(self) -> dict:
        total = 0
        files = 0
        try:
            for entry in os.scandir(self.dir):
                try:
                    # 索引是派生物，不算进「存储占用」：删了会自动重建，
                    # 把它算进去会让用户看到一份永远对不上的数字。
                    if (entry.is_file() and entry.name.endswith(".json")
                            and not entry.name.startswith("_")):
                        total += entry.stat().st_size
                        files += 1
                except OSError:
                    continue
        except OSError:
            return {"bytes": 0, "files": 0}
        return {"bytes": total, "files": files}
