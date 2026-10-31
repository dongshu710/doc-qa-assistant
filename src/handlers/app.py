"""组合根：把运行时依赖装配起来，再把路由类拼成一个 Handler。

为什么单独一层：`create_server()` 原来同时负责「建依赖」和「定义 30 多个路由方法」，
2241 行里两种关注点缠在一起，改一个上传接口要在一屏之外找对应的鉴权。
现在依赖只在这里组装，路由在 base/resources/read/write 四个文件里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

from .. import (appconfig, kbstore,
                settings_ops)
from .. import update as update_mod
from ..auth import ApiKeyStore
from ..config import api_key, load_settings
from ..guards import Guards
from ..metrics_exporter import Metrics
from ..notes.service import NoteService
from ..pipeline import RAGPipeline
from ..version import __version__
from .common import (_knowledge_dir, _raw_dir)

from ..http_server import BoundedHTTPServer
from .base import make_base
from .read import make_read
from .resources import make_resources
from .write import make_write


@dataclass
class AppDeps:
    """组合根传给各路由模块的依赖。

    原来是 `SimpleNamespace`：拼错一个字段名不会报错，只在运行时 AttributeError，
    而症状是「某个接口 500」——离出错的地方隔着几层调用。dataclass 在构造时
    就校验全部字段，少给一个立即 TypeError，拼错一个也立即 TypeError。

    带前导下划线的几个是被各模块当函数直接调用的闭包（`_reopen_notes` 等），
    与普通数据字段放在一起是历史原因，不是刻意区分。
    """

    project_root: str
    settings: Any
    metrics: Any
    pipe: Any
    store: Any
    log_dir: str
    guards: Any
    api_keys: Any
    note_ref: dict
    feedback_path: str
    feedback_cases_path: str
    doc_cases_path: str
    run_report_path: str
    raw_dir: str
    kb_dir: str
    async_reload: bool
    reload_kb: Any
    index_payload: Any
    index_fields: Any
    _reopen_notes: Any
    _repo_url: Any
    _downloads: Any
    _mcp_config: Any
    _probe_llm: Any
    _storage_report: Any
    _clear_index: Any
    _total_bytes: Any
    _settings_payload: Any
    _runtime_warnings: Any
    _setup_state: Any
    _apply_setup: Any
    _mcp_targets: Any
    _picker_command: Any
    _pick_folder: Any
    _count_notes: Any
    _copy_notes: Any


def build_app(host: str, port: int, knowledge_dir: str | None = None):
    # 本文件在 src/handlers/ 下：项目根要退三层，退两层会算成 src/
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    settings = load_settings()
    metrics = Metrics(enabled=True)
    # 显式传入目录 = 传统单目录模式（测试与批量导入用）；否则走版本库 + 审批流
    store: kbstore.KnowledgeStore | None = None
    if knowledge_dir is None and settings.kb_store not in ("off", "0", "false", "no"):
        kb_root = settings.kb_dir if os.path.isabs(settings.kb_dir) else os.path.join(project_root, settings.kb_dir)
        seed = settings.kb_seed_dir if os.path.isabs(settings.kb_seed_dir) else os.path.join(project_root, settings.kb_seed_dir)
        store = kbstore.KnowledgeStore(kb_root, seed_dir=seed,
                                       keep_versions=settings.kb_keep_versions)
        store.bootstrap()
        pipe = RAGPipeline(store.active_dir())
    else:
        pipe = RAGPipeline(knowledge_dir or _knowledge_dir())

    log_dir = os.path.dirname(pipe.log_path)
    guards = Guards(pipe.settings, log_dir)
    api_keys = ApiKeyStore(pipe.settings.api_keys)
    try:
        note_ref: dict = {"service": NoteService(), "error": None}
    except OSError as exc:  # 目录不可写等情况：接口回 503，问答照常
        note_ref = {"service": None, "error": f"{type(exc).__name__}: {exc}"}

    feedback_path = os.path.join(log_dir, "feedback.jsonl")
    feedback_cases_path = os.path.join(project_root, "tests", "eval_cases_feedback.jsonl")
    raw_dir = _raw_dir()
    doc_cases_path = os.path.join(project_root, "tests", "eval_cases_docs.jsonl")
    run_report_path = os.path.join(project_root, "tests", "report_doc_cases.json")

    def kb_dir() -> str:
        """活动版本目录；审批通过后只换这个指针，不在原目录上打补丁。"""
        # 异步重建期间 pipe.knowledge_dir 还是旧的，列表必须以版本库为准，
        # 否则刚上传的文件在页面上“消失”几秒。
        return store.active_dir() if store is not None else pipe.knowledge_dir

    def async_reload() -> bool:
        # 传统单目录模式（测试/批量导入）保持同步：调用方拿到的 chunks 必须是最终值。
        return store is not None and (pipe.settings.kb_async_reload or "on").strip().lower() == "on"

    def reload_kb(wait: bool | None = None) -> int | None:
        """重建索引。默认按 KB_ASYNC_RELOAD 走后台；返回 None 表示“已排队”。"""
        target = store.active_dir() if store is not None else None
        if wait is None:
            wait = not async_reload()
        if wait:
            return pipe.reload(target or pipe.knowledge_dir)
        pipe.reload_async(target or pipe.knowledge_dir)
        return None

    def index_payload() -> dict:
        return pipe.rebuild_state()

    def index_fields(before: int | None = None) -> dict:
        """接口响应用的索引字段：重建中时 chunks 返回 null，避免报旧值误导。"""
        state = pipe.rebuild_state()
        building = bool(state.get("rebuilding"))
        out = {"rebuilding": building, "index": state,
               "chunks": None if building else len(pipe.chunks)}
        if before is not None:
            out["added_chunks"] = None if building else len(pipe.chunks) - before
        return out

    def _reopen_notes() -> dict:
        """存储位置变了就重建笔记服务：旧实例的路径与缓存都指向老目录，不能复用。"""
        try:
            note_ref["service"] = NoteService()
            note_ref["error"] = None
            return {"ok": True, "home": str(note_ref["service"].store.home)}
        except OSError as exc:
            note_ref["error"] = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "message": note_ref["error"]}

    _repo_cache = {"stamp": None, "url": ""}

    def _repo_url() -> str:
        """从 .git/config 读 origin，换 fork 也不用改代码；读不到就给个能点的默认值。

        按 (mtime_ns, size) 缓存：`/api/settings` 每次都要算下载地址，
        而 `.git/config` 几乎不变，没必要每个请求都读一遍盘。
        """
        config_path = pathlib.Path(project_root) / ".git" / "config"
        try:
            stat = config_path.stat()
        except OSError:
            return ""
        stamp = (stat.st_mtime_ns, stat.st_size)
        if _repo_cache["stamp"] == stamp:
            return _repo_cache["url"]
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError:
            return ""
        found = re.search(r"url\s*=\s*(\S+)", text)
        url = ""
        if found:
            match = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", found.group(1))
            if match:
                url = f"https://github.com/{match.group(1)}/{match.group(2)}"
        _repo_cache.update(stamp=stamp, url=url)
        return url

    def _downloads() -> dict:
        """两种下载入口：整包（问答+笔记）与插件包（只有笔记）。页面按钮直接指到这里。"""
        repo = _repo_url()
        if not repo:
            return {"page": "", "app": "", "plugin": ""}
        names = update_mod.asset_names(__version__)
        base = f"{repo}/releases/latest/download"
        return {"page": f"{repo}/releases/latest",
                "app": f"{base}/{names['app']}",
                "plugin": f"{base}/{names['plugin']}"}

    def _mcp_config() -> dict:
        """生成 MCP 客户端配置；实现放在 settings_ops，这里只负责取当前实际路径。"""
        service = note_ref["service"]
        home = str(service.store.home) if service else str(pathlib.Path.home() / "agent-notes")
        return settings_ops.mcp_config(sys.executable, project_root, home)

    def _probe_llm(cfg: dict) -> dict:
        """真打一次 minimal 请求验证配置。实现见 settings_ops.probe_llm（可单测）。"""
        return settings_ops.probe_llm(cfg.get("base_url"), cfg.get("model"), cfg.get("api_key"))

    def _storage_report(fresh: bool = False) -> dict:
        service = note_ref["service"]
        home = str(service.store.home) if service else ""
        index_dir = settings.embedding_index_dir
        if index_dir and not os.path.isabs(index_dir):
            index_dir = os.path.join(project_root, index_dir)
        return settings_ops.storage_report(
            notes_home=home,
            kb_root=str(store.root) if store is not None else "",
            index_dir=index_dir,
            config_path=str(appconfig.path()),
            keep_versions=appconfig.keep_versions(),
            fresh=fresh,
        )

    def _clear_index(home: str) -> int:
        return settings_ops.clear_index(home) if home else 0

    def _total_bytes(report: dict) -> int:
        """存储区总占用。必须与 `storage_report()` 的字段保持同一份清单——

        少列一项不会报错，只会让「清理前看到 200 MB、清理后还是 200 MB」这种
        对不上的事情出现。`assets` 是 1.26.0 加的，这里漏过一次。
        """
        return sum(int((report.get(key) or {}).get("bytes") or 0)
                   for key in ("notes", "assets", "index", "kb", "config", "embedding"))

    def _settings_payload() -> dict:
        live = load_settings()
        view = appconfig.view()
        service = note_ref["service"]
        home = str(service.store.home) if service else ""
        # 笔记篇数直接取存储统计的结果：两边都数的是 notes/*.md，
        # 分开数就是同一棵树走两遍（千篇时多花 10 ms 以上，且两次结果可能不一致）。
        storage = _storage_report()
        count = int((storage.get("notes") or {}).get("files") or 0)
        return {
            "ok": True,
            "llm": {
                **view["llm"],
                "effective_base_url": live.api_base,
                "effective_model": live.model,
                "key_ready": bool(api_key()),
            },
            "notes": {
                **view["notes"],
                "home_effective": home,
                "home_default": str(pathlib.Path.home() / "agent-notes"),
                "available": service is not None,
                "error": note_ref["error"],
                "count": count,
                "backup": appconfig.backup_state(count),
            },
            "mcp": _mcp_config(),
            "mcp_targets": _mcp_targets(),
            "repo_url": _repo_url(),
            "downloads": _downloads(),
            "storage": storage,
            "config_path": view["config_path"],
            "config_error": view.get("config_error") or "",
            "config_backup": view.get("config_backup") or "",
            "updated_at": view["updated_at"],
        }

    def _runtime_warnings() -> list[str]:
        """把「能跑但已经降级」的状态汇总成一句句人话，供 /api/health 与页面提示。

        为什么需要：Redis 抖动退回内存、embedding 建库失败退回 n-gram，
        这些都不影响出答案，所以最容易被忽略——而它们直接改变答案质量与成本口径。
        """
        out: list[str] = []
        try:
            status = guards.status()
        except Exception:  # noqa: BLE001 —— 健康检查本身不能 500
            return out
        for name, hits in (status.get("fallbacks") or {}).items():
            if hits:
                out.append(f"{name} 已退回进程内状态（累计 {hits} 次），多实例下不再一致")
        if status.get("redis_error"):
            out.append(f"Redis 不可用：{status['redis_error']}")
        # 写盘失败原来被 except OSError: pass 吞掉：磁盘满了界面一切正常，
        # 但预算归零、灰度回到默认值、审计日志在丢。
        persist = status.get("persist") or {}
        for name, label in (("cost", "每日用量预算"), ("canary", "灰度配置"), ("audit", "审计日志")):
            item = persist.get(name) or {}
            if item.get("failures"):
                out.append(f"{label}写盘失败 {item['failures']} 次"
                           f"（{item.get('error') or '未知原因'}），重启后会回退到默认值")
        detail = pipe.retrieval_detail or {}
        if detail.get("fallback_error"):
            out.append(f"检索未按配置运行：{detail['fallback_error']}")
        if detail.get("degraded"):
            out.append("embedding 最近一次调用失败，当前为词法兜底")
        if note_ref["service"] is None:
            out.append(f"笔记存储不可用：{note_ref['error']}")
        return out

    def _setup_state() -> dict:
        """首次运行引导的状态：没建过存储区就要提示，建过就不再打扰。"""
        service = note_ref["service"]
        home = str(service.store.home) if service else ""
        count = _count_notes(home) if home else 0
        # 老用户升级上来时目录里已经有笔记：默认值给现有位置，别让人「重新建一个空库」
        suggested = home if count else str(pathlib.Path.home() / "记忆文档")
        return {
            "ok": True,
            "needed": not appconfig.setup_done(),
            "home": home,
            "default_home": suggested,
            "notes": count,
            "exists": bool(suggested) and os.path.isdir(suggested),
            "platform": sys.platform,
        }

    def _apply_setup(home: str, client: str = "") -> tuple[dict, int]:
        """建存储区：目录、说明文件、配置一次写全，然后重建笔记服务。

        失败必须说清是哪一步失败的（不可写 / 是文件 / 建目录失败），
        否则用户只会看到「设置失败」四个字，不知道去改什么。
        """
        text = appconfig.clean_path(home)
        if not text:
            return {"ok": False, "error": "invalid_argument", "message": "先选一个存放位置"}, 400
        target = pathlib.Path(text).expanduser()
        if not target.is_absolute():
            return {"ok": False, "error": "invalid_argument",
                    "message": "填绝对路径，例如 D:////记忆文档"}, 400
        if target.exists() and not target.is_dir():
            return {"ok": False, "error": "invalid_argument",
                    "message": f"{target} 是个文件，不能当存储区"}, 400
        created = []
        try:
            target.mkdir(parents=True, exist_ok=True)
            for name in ("notes", "threads", "index", "exports", "assets"):
                path = target / name
                if not path.exists():
                    path.mkdir(parents=True, exist_ok=True)
                    created.append(name)
            probe = target / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            return {"ok": False, "error": "io_error",
                    "message": f"这个位置不可写：{exc}"}, 400
        try:
            appconfig.update({"notes": {"home": str(target)},
                              "setup": {"done": True}})
        except ValueError as exc:
            return {"ok": False, "error": "invalid_argument", "message": str(exc)}, 400
        reopened = _reopen_notes()
        if not reopened.get("ok"):
            # 目录建好了但服务没起来：配置保留，报错让人能重试，不要假装成功
            return {"ok": False, "error": "notes_unavailable",
                    "message": f"目录已建好，但笔记服务启动失败：{reopened.get('message')}",
                    "home": str(target)}, 500
        guards.audit.write("setup.done", client=client, home=str(target), created=created)
        return {"ok": True, "home": str(target), "created": created,
                "notes": _count_notes(str(target))}, 200

    def _mcp_targets() -> list[dict]:
        """各 MCP 客户端的配置位置；实现放在 settings_ops 以便单测。

        只返回已知客户端，不接受调用方传路径——这个接口会写别人的配置文件，
        开放任意路径等于开了个本地任意写文件的洞。
        """
        return settings_ops.mcp_targets()

    pick_lock = threading.Lock()      # 连点两次不能弹两个框

    def _picker_command() -> list[str] | None:
        """各平台的原生目录选择器。找不到就返回 None，让前端回退到手输。"""
        if os.name == "nt":
            exe = shutil.which("powershell") or shutil.which("pwsh")
            if not exe:
                return None
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$d.Description='选择笔记存储位置';"
                "$d.ShowNewFolderButton=$true;"
                "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
                "{[Console]::Out.Write($d.SelectedPath)}"
            )
            cmd = [exe, "-NoProfile", "-Command", script]
            # Windows PowerShell 5.1 需要 -STA 才能弹 WinForms；pwsh 7 默认就是 STA，传了反而报错
            if os.path.basename(exe).lower().startswith("powershell"):
                cmd.insert(2, "-STA")
            return cmd
        if sys.platform == "darwin":
            return ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择笔记存储位置")']
        if shutil.which("zenity"):
            return ["zenity", "--file-selection", "--directory", "--title=选择笔记存储位置"]
        if shutil.which("kdialog"):
            return ["kdialog", "--getexistingdirectory", str(pathlib.Path.home())]
        return None

    def _pick_folder() -> tuple[int, dict]:
        """弹系统原生目录选择框，返回 (HTTP 状态, 响应体)。

        浏览器拿不到本机路径，只能由服务进程在桌面会话里弹。
        独立子进程执行：不占 HTTP 线程，也不和 GUI 主线程纠缠；
        取消 / 超时 / 无图形环境都返回结构化结果，前端据此回退到手输。
        """
        if (os.environ.get("SETTINGS_PICKER") or "").strip().lower() in ("off", "0", "false"):
            return 200, {"ok": False, "error": "disabled", "message": "目录选择已关闭，请手动填路径"}
        if not pick_lock.acquire(timeout=1):
            return 429, {"ok": False, "error": "busy", "message": "已经有一个选择窗口开着"}
        try:
            cmd = _picker_command()
            if not cmd:
                return 200, {"ok": False, "error": "unsupported",
                             "message": "这个系统没有可用的目录选择器，请手动填路径"}
            started = time.monotonic()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=180)
            except subprocess.TimeoutExpired:
                return 200, {"ok": False, "error": "timeout", "message": "等了 180 秒没有选择，已取消"}
            except OSError as exc:
                return 200, {"ok": False, "error": "unsupported", "message": f"弹不出选择框：{exc}"}
            path = appconfig.clean_path(proc.stdout or "")
            if proc.returncode != 0 or not path:
                return 200, {"ok": False, "error": "cancelled", "message": "已取消"}
            return 200, {"ok": True, "path": path,
                         "elapsed_ms": int((time.monotonic() - started) * 1000)}
        finally:
            pick_lock.release()

    def _count_notes(home: str) -> int:
        return settings_ops.count_notes(home)

    def _copy_notes(src: str, dst: str) -> dict:
        return settings_ops.copy_notes(src, dst)


    deps = AppDeps(
        project_root=project_root, settings=settings, metrics=metrics, pipe=pipe,
        store=store, log_dir=log_dir, guards=guards, api_keys=api_keys,
        note_ref=note_ref, feedback_path=feedback_path,
        feedback_cases_path=feedback_cases_path, doc_cases_path=doc_cases_path,
        run_report_path=run_report_path, raw_dir=raw_dir, kb_dir=kb_dir,
        async_reload=async_reload, reload_kb=reload_kb, index_payload=index_payload,
        index_fields=index_fields, _reopen_notes=_reopen_notes, _repo_url=_repo_url,
        _downloads=_downloads, _mcp_config=_mcp_config, _probe_llm=_probe_llm,
        _storage_report=_storage_report, _clear_index=_clear_index,
        _total_bytes=_total_bytes, _settings_payload=_settings_payload,
        _runtime_warnings=_runtime_warnings, _setup_state=_setup_state,
        _apply_setup=_apply_setup, _mcp_targets=_mcp_targets,
        _picker_command=_picker_command, _pick_folder=_pick_folder,
        _count_notes=_count_notes, _copy_notes=_copy_notes,
    )
    ReadRoutes = make_read(deps)
    WriteRoutes = make_write(deps)
    ResourceRoutes = make_resources(deps)
    BaseRoutes = make_base(deps)

    class Handler(ReadRoutes, WriteRoutes, ResourceRoutes, BaseRoutes):
        # HEAD 复用 GET：BaseHTTPRequestHandler 会把 HEAD 当独立方法找，
        # 不显式绑定就会 501（浏览器的预检与部分客户端会先发 HEAD）。
        do_HEAD = ReadRoutes.do_GET

    httpd = BoundedHTTPServer((host, port), Handler)
    return httpd, pipe
