"""知识库版本目录 + 审批流 + 按文档粒度回滚。

目录结构（`data/kb/`）：
```
versions/v0001/
  manifest.json          # 版本元数据：作者、来源、每份文档的 sha256
  files/*.md
versions/v0002/...
pending/chg_0001/
  request.json           # 待审批变更：作者、说明、新增/删除清单
  files/*.md
changes/chg_0001.json    # 已审批/已拒绝的历史（只增不改）
state.json               # {"active": "v0002", "next_version": 3, ...}
```

三条不变量：
1. **版本只增不改**：回滚不是把指针拨回去，而是用旧内容生成一个新版本，
   历史始终可追溯（谁、何时、从哪个版本恢复）。
2. **激活是原子的**：版本目录写完后，才用 `os.replace` 更新 `state.json`；
   读侧只认 `state.json`，不会看到半成品。
3. **按文档回滚**：只替换目标文件，其余文档保持当前版本，避免「为回滚一份
   文档把别人刚发布的内容也退回去」。

并发：本地文件锁（`state.lock`）保证同机多进程串行；多实例部署时审批是低频
管理动作，建议只让一个实例处理，或把锁换成 Redis 锁。上传本身不写活动目录，
所以不会出现「两个实例各写一半」。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone

ALLOWED_EXT = (".md", ".txt")


class KnowledgeError(RuntimeError):
    """知识库操作失败（名称非法、版本不存在、状态冲突等）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _safe_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise KnowledgeError(f"非法文件名: {name!r}")
    if not raw.lower().endswith(ALLOWED_EXT):
        raise KnowledgeError(f"只支持 .md / .txt: {name!r}")
    if len(raw) > 80 or any(ch in raw for ch in '<>:"|?*\x00'):
        raise KnowledgeError(f"非法文件名: {name!r}")
    return raw


class _FileLock:
    """跨进程互斥：O_EXCL 创建锁文件，超时 5s；30s 未释放视为残留。"""

    def __init__(self, path: str, timeout_s: float = 5.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.time() + self.timeout_s
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                    if age > 30:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    raise KnowledgeError("知识库正被其他进程修改，请稍后重试")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


class KnowledgeStore:
    def __init__(self, root: str, seed_dir: str | None = None):
        self.root = os.path.abspath(root)
        self.seed_dir = os.path.abspath(seed_dir) if seed_dir else None
        self.versions_dir = os.path.join(self.root, "versions")
        self.pending_dir = os.path.join(self.root, "pending")
        self.changes_dir = os.path.join(self.root, "changes")
        self.state_path = os.path.join(self.root, "state.json")
        self.lock_path = os.path.join(self.root, "state.lock")
        for path in (self.versions_dir, self.pending_dir, self.changes_dir):
            os.makedirs(path, exist_ok=True)

    # ---------- 状态 ----------
    def _state(self) -> dict:
        if not os.path.exists(self.state_path):
            return {"active": None, "next_version": 1, "next_change": 1, "updated_at": _now()}
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise KnowledgeError(f"state.json 损坏: {exc}") from exc
        return {
            "active": data.get("active"),
            "next_version": max(1, int(data.get("next_version") or 1)),
            "next_change": max(1, int(data.get("next_change") or 1)),
            "updated_at": data.get("updated_at") or _now(),
        }

    def _write_state(self, state: dict) -> None:
        state["updated_at"] = _now()
        _atomic_json(self.state_path, state)

    def version_dir(self, version: str) -> str:
        return os.path.join(self.versions_dir, version)

    def active_version(self) -> str:
        active = self._state().get("active")
        if not active:
            raise KnowledgeError("知识库尚未初始化")
        return active

    def active_dir(self) -> str:
        return os.path.join(self.version_dir(self.active_version()), "files")

    # ---------- 初始化 ----------
    def bootstrap(self) -> dict:
        with _FileLock(self.lock_path):
            state = self._state()
            if state.get("active") and os.path.isdir(self.version_dir(state["active"])):
                return self.status()
            # 有历史版本但 state 丢了：取最新版本作为活动版本
            existing = sorted(name for name in os.listdir(self.versions_dir)
                              if name.startswith("v") and os.path.isdir(self.version_dir(name)))
            if existing:
                state["active"] = existing[-1]
                state["next_version"] = max(state["next_version"],
                                            int(existing[-1][1:]) + 1 if existing[-1][1:].isdigit() else 1)
                self._write_state(state)
                return self.status()

            if not self.seed_dir or not os.path.isdir(self.seed_dir):
                raise KnowledgeError(f"初始知识库目录不存在: {self.seed_dir}")
            files = {}
            for name in sorted(os.listdir(self.seed_dir)):
                if name.lower().endswith(ALLOWED_EXT):
                    with open(os.path.join(self.seed_dir, name), "rb") as f:
                        files[name] = f.read()
            if not files:
                raise KnowledgeError(f"初始知识库为空: {self.seed_dir}")
            version = f"v{state['next_version']:04d}"
            self._write_version(version, files, parent=None, kind="bootstrap",
                                author="system", note=f"从 {self.seed_dir} 导入",
                                change_id=None, approved_by="system")
            state["active"] = version
            state["next_version"] += 1
            self._write_state(state)
            return self.status()

    # ---------- 版本写入 ----------
    def _write_version(self, version: str, files: dict[str, bytes], parent: str | None,
                       kind: str, author: str, note: str, change_id: str | None,
                       approved_by: str, restored_from: str | None = None,
                       deletes: list[str] | None = None) -> dict:
        target = self.version_dir(version)
        if os.path.exists(target):
            raise KnowledgeError(f"版本已存在: {version}")
        files_dir = os.path.join(target, "files")
        os.makedirs(files_dir)
        docs = []
        for name in sorted(files):
            data = files[name]
            with open(os.path.join(files_dir, name), "wb") as f:
                f.write(data)
            docs.append({"name": name, "sha256": _sha256(data), "size": len(data)})
        manifest = {
            "version": version,
            "created_at": _now(),
            "kind": kind,
            "parent": parent,
            "author": author,
            "approved_by": approved_by,
            "note": note,
            "change_id": change_id,
            "restored_from": restored_from,
            "deletes": deletes or [],
            "docs": docs,
        }
        _atomic_json(os.path.join(target, "manifest.json"), manifest)
        return manifest

    def _read_manifest(self, version: str) -> dict:
        path = os.path.join(self.version_dir(version), "manifest.json")
        if not os.path.exists(path):
            raise KnowledgeError(f"版本不存在: {version}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _read_files(self, version: str) -> dict[str, bytes]:
        folder = os.path.join(self.version_dir(version), "files")
        if not os.path.isdir(folder):
            raise KnowledgeError(f"版本文件缺失: {version}")
        files = {}
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(ALLOWED_EXT):
                with open(os.path.join(folder, name), "rb") as f:
                    files[name] = f.read()
        return files

    # ---------- 审批 ----------
    def stage(self, files: dict[str, bytes | str], author: str, note: str = "",
              deletes: list[str] | None = None) -> dict:
        normalized: dict[str, bytes] = {}
        for name, data in (files or {}).items():
            safe = _safe_name(name)
            normalized[safe] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        deletes = [_safe_name(n) for n in (deletes or [])]
        if not normalized and not deletes:
            raise KnowledgeError("变更内容为空")

        with _FileLock(self.lock_path):
            state = self._state()
            active = state.get("active")
            if not active:
                raise KnowledgeError("知识库尚未初始化")
            active_files = self._read_files(active)
            for name in deletes:
                if name not in active_files:
                    raise KnowledgeError(f"当前版本没有这份文档: {name}")
            if not normalized and len(deletes) >= len(active_files):
                raise KnowledgeError("知识库至少要保留一个文件")

            change_id = f"chg_{state['next_change']:04d}"
            folder = os.path.join(self.pending_dir, change_id)
            os.makedirs(os.path.join(folder, "files"))
            for name, data in normalized.items():
                with open(os.path.join(folder, "files", name), "wb") as f:
                    f.write(data)
            request = {
                "change_id": change_id,
                "status": "pending",
                "created_at": _now(),
                "author": author,
                "note": note[:300],
                "base_version": active,
                "files": [{"name": n, "sha256": _sha256(d), "size": len(d),
                           "action": "update" if n in active_files else "add"}
                          for n, d in sorted(normalized.items())],
                "deletes": deletes,
                # 风险提示只做客观陈述，不替审批人下结论
                "warnings": ([f"将覆盖现有文档: {', '.join(sorted(set(normalized) & set(active_files)))}"]
                             if set(normalized) & set(active_files) else [])
                            + ([f"将删除文档: {', '.join(deletes)}"] if deletes else []),
            }
            _atomic_json(os.path.join(folder, "request.json"), request)
            state["next_change"] += 1
            self._write_state(state)
            return {"change": request, "active": active}

    def _load_request(self, change_id: str) -> dict:
        path = os.path.join(self.pending_dir, change_id, "request.json")
        if not os.path.exists(path):
            raise KnowledgeError(f"待审批变更不存在: {change_id}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def approve(self, change_id: str, approver: str, note: str = "") -> dict:
        with _FileLock(self.lock_path):
            request = self._load_request(change_id)
            if request.get("status") != "pending":
                raise KnowledgeError(f"变更状态为 {request.get('status')}，不能重复审批")
            state = self._state()
            active = state.get("active")
            if request.get("base_version") != active:
                raise KnowledgeError(
                    f"变更基于 {request.get('base_version')}，当前活动版本已是 {active}；"
                    "请让提交者基于最新版本重新提交"
                )
            files = self._read_files(active)
            staged_dir = os.path.join(self.pending_dir, change_id, "files")
            for name in sorted(os.listdir(staged_dir)):
                if name.lower().endswith(ALLOWED_EXT):
                    with open(os.path.join(staged_dir, name), "rb") as f:
                        files[name] = f.read()
            for name in request.get("deletes") or []:
                files.pop(name, None)
            if not files:
                raise KnowledgeError("审批后知识库为空，已拒绝")

            version = f"v{state['next_version']:04d}"
            manifest = self._write_version(
                version, files, parent=active, kind="change", author=request.get("author", ""),
                note=note or request.get("note", ""), change_id=change_id,
                approved_by=approver, deletes=request.get("deletes") or [],
            )
            state["active"] = version
            state["next_version"] += 1
            self._write_state(state)

            request.update({"status": "approved", "decided_at": _now(),
                            "approver": approver, "version": version,
                            "decision_note": note[:300]})
            _atomic_json(os.path.join(self.changes_dir, f"{change_id}.json"), request)
            shutil.rmtree(os.path.join(self.pending_dir, change_id), ignore_errors=True)
            return {"change_id": change_id, "version": version, "manifest": manifest}

    def reject(self, change_id: str, approver: str, reason: str = "") -> dict:
        with _FileLock(self.lock_path):
            request = self._load_request(change_id)
            if request.get("status") != "pending":
                raise KnowledgeError(f"变更状态为 {request.get('status')}，不能重复审批")
            request.update({"status": "rejected", "decided_at": _now(),
                            "approver": approver, "reason": reason[:300]})
            _atomic_json(os.path.join(self.changes_dir, f"{change_id}.json"), request)
            shutil.rmtree(os.path.join(self.pending_dir, change_id), ignore_errors=True)
            return {"change_id": change_id, "status": "rejected"}

    # ---------- 文档级回滚 ----------
    def rollback_doc(self, name: str, to_version: str, author: str, note: str = "") -> dict:
        name = _safe_name(name)
        with _FileLock(self.lock_path):
            state = self._state()
            active = state.get("active")
            if not active:
                raise KnowledgeError("知识库尚未初始化")
            source = self._read_files(to_version)
            if name not in source:
                raise KnowledgeError(f"{to_version} 中没有 {name}")
            current = self._read_files(active)
            if name not in current:
                raise KnowledgeError(f"当前版本没有 {name}；新增文档请走上传流程")

            files = dict(current)
            files[name] = source[name]
            version = f"v{state['next_version']:04d}"
            manifest = self._write_version(
                version, files, parent=active, kind="rollback_doc", author=author,
                note=note or f"{name} 回滚到 {to_version}", change_id=None,
                approved_by=author, restored_from=to_version,
            )
            state["active"] = version
            state["next_version"] += 1
            self._write_state(state)
            return {"version": version, "restored": name, "from": to_version,
                    "manifest": manifest}

    # ---------- 查询 ----------
    def versions(self) -> list[dict]:
        rows = []
        for name in sorted(os.listdir(self.versions_dir)):
            if not name.startswith("v"):
                continue
            try:
                rows.append(self._read_manifest(name))
            except (KnowledgeError, OSError, json.JSONDecodeError):
                continue
        return rows

    def changes(self, status: str | None = None) -> list[dict]:
        rows = []
        if os.path.isdir(self.pending_dir):
            for name in sorted(os.listdir(self.pending_dir)):
                path = os.path.join(self.pending_dir, name, "request.json")
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        rows.append(json.load(f))
        if os.path.isdir(self.changes_dir):
            for name in sorted(os.listdir(self.changes_dir)):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(self.changes_dir, name), encoding="utf-8") as f:
                    rows.append(json.load(f))
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def doc_history(self, name: str) -> list[dict]:
        name = _safe_name(name)
        history = []
        for manifest in self.versions():
            for doc in manifest.get("docs") or []:
                if doc.get("name") == name:
                    history.append({"version": manifest["version"],
                                    "created_at": manifest.get("created_at"),
                                    "sha256": doc.get("sha256"),
                                    "size": doc.get("size"),
                                    "kind": manifest.get("kind"),
                                    "author": manifest.get("author")})
        return history

    def status(self) -> dict:
        state = self._state()
        active = state.get("active")
        docs = 0
        if active:
            try:
                docs = len(self._read_files(active))
            except KnowledgeError:
                docs = 0
        pending = 0
        if os.path.isdir(self.pending_dir):
            pending = sum(1 for n in os.listdir(self.pending_dir)
                          if os.path.exists(os.path.join(self.pending_dir, n, "request.json")))
        return {
            "active": active,
            "versions": len([n for n in os.listdir(self.versions_dir) if n.startswith("v")]),
            "pending_changes": pending,
            "docs": docs,
        }

    def read_doc(self, name: str, version: str | None = None) -> bytes:
        name = _safe_name(name)
        vid = version or self.active_version()
        path = os.path.join(self.version_dir(vid), "files", name)
        if not os.path.exists(path):
            raise KnowledgeError(f"{vid} 中没有 {name}")
        with open(path, "rb") as f:
            return f.read()
