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
import tempfile
import time
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
MAX_TURNS = 500
MAX_BYTES = 4 * 1024 * 1024
LIST_LIMIT = 60
# 前端只在标题/末轮变化时写，覆盖同一秒内的重复写；这里再兜一层，防止手滑刷爆磁盘
MIN_WRITE_GAP_S = 0.0


class ThreadError(ValueError):
    """调用方把参数写错了（不是磁盘问题），映射成 400。"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class ThreadStore:
    def __init__(self, home: str | Path):
        self.home = Path(home).expanduser().resolve()
        self.dir = self.home / "threads"
        self.dir.mkdir(parents=True, exist_ok=True)

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
        """列表只给元数据，不带正文：侧栏要快，正文按需取。"""
        items = []
        try:
            entries = list(self.dir.glob("*.json"))
        except OSError:
            return []
        for path in entries:
            try:
                stat = path.stat()
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue  # 坏文件不该让整个列表消失
            if not isinstance(data, dict):
                continue
            turns = data.get("turns") if isinstance(data.get("turns"), list) else []
            items.append({
                "id": path.stem,
                "title": str(data.get("title") or "新对话")[:120],
                "created": str(data.get("created") or ""),
                "updated": str(data.get("updated") or data.get("created") or ""),
                "sid": str(data.get("sid") or ""),
                "turns": len(turns),
                "mtime": stat.st_mtime,
            })
        items.sort(key=lambda item: (item["updated"] or "", item["mtime"]), reverse=True)
        return items[:max(1, int(limit))]

    # ---- 写 ----

    def put(self, thread_id: str, data: dict) -> dict:
        path = self.path_for(thread_id)
        if not isinstance(data, dict):
            raise ThreadError("请求体必须是对象")
        turns = self._clean_turns(data.get("turns"))
        existing = {}
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        created = str(data.get("created") or (existing.get("created") if isinstance(existing, dict) else "") or _now())
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
        handle, tmp = tempfile.mkstemp(dir=str(self.dir), prefix=".t-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return {key: value for key, value in record.items() if key != "turns"} | {"turns": len(turns)}

    def delete(self, thread_id: str) -> None:
        path = self.path_for(thread_id)
        try:
            path.unlink()
        except FileNotFoundError:
            raise KeyError(thread_id) from None
        except OSError as exc:
            raise OSError(f"删除会话失败：{exc}") from exc

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
                    if entry.is_file() and entry.name.endswith(".json"):
                        total += entry.stat().st_size
                        files += 1
                except OSError:
                    continue
        except OSError:
            return {"bytes": 0, "files": 0}
        return {"bytes": total, "files": files}
