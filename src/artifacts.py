"""运行时产物的落点：跟数据走，不跟代码走。

这三个文件是**运行时长出来的**（用户点「存为用例」、生成 docs 用例、跑用例留结果），
而它们的路径原来写死在 `handlers/app.py` 与 `report.py` 两处。两个后果都不会报错：

1. `pip install` 之后，`tests/` 在 site-packages 里，可能只读——写失败只表现为
   「点了没反应」，日志里一行都没有；
2. 用户删掉 `tests/` 清理仓库，会连带删掉自己积累的反馈用例，而页面上数字变小
   看起来像「本来就没有」。

所以落点跟笔记存储区一起走（那已经是用户数据目录），代码目录只读。

为什么不做成「配置项」：多一个必须填的配置项，就多一个填错的机会。默认值必须是对的。
"""
from __future__ import annotations

import os
import shutil

# 只有这三个是运行时长出来的。其余评测报告（baseline.json / report_l3.json 等）
# 是工具产物，跟着代码走，不进这个目录。
RUNTIME_FILES = (
    "eval_cases_feedback.jsonl",
    "eval_cases_docs.jsonl",
    "report_doc_cases.json",
)
LEGACY_SUBDIR = "tests"

# 启动时由组合根写入一次，之后只读。放在模块级是因为 report.py 与 evaluator.py
# 都可能在「没有 deps」的上下文里被调用（CLI、单测），让它们各自重算一遍路径，
# 就会出现「页面写 A、评测读 B」这种最难查的分叉。
_ACTIVE: dict[str, str] = {}


def default_dir(home: str | None) -> str:
    """`ARTIFACTS_DIR` 优先；否则放笔记存储区下；再没有就落到用户主目录。"""
    configured = (os.environ.get("ARTIFACTS_DIR") or "").strip()
    if configured:
        return configured
    if home:
        return os.path.join(home, "artifacts")
    return os.path.join(os.path.expanduser("~"), ".jiyi", "artifacts")


def resolve(project_root: str, home: str | None = None) -> dict[str, str]:
    """返回 name → 绝对路径，并把旧位置（`<项目根>/tests/`）里已有的文件复制过去。

    复制而不是移动：旧文件留在原地，核对后由用户自己删；万一要回退旧版本，数据还在。
    目标已存在就跳过——迁移只发生一次，绝不覆盖新数据。
    """
    target_dir = default_dir(home)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        # 目录建不出来（只读盘、权限）：退回旧位置继续跑，但要让人看见这件事
        print(f"[警告] 无法创建产物目录 {target_dir}：{exc}；退回项目内 tests/")
        target_dir = os.path.join(project_root, LEGACY_SUBDIR)

    paths: dict[str, str] = {}
    for name in RUNTIME_FILES:
        target = os.path.join(target_dir, name)
        legacy = os.path.join(project_root, LEGACY_SUBDIR, name)
        if not os.path.exists(target) and os.path.exists(legacy):
            try:
                shutil.copy2(legacy, target)
                print(f"[迁移] {name} → {target_dir}（旧文件保留，核对后可删除）")
            except OSError as exc:
                print(f"[警告] 迁移 {name} 失败：{exc}；继续读写旧位置")
                paths[name] = legacy
                continue
        paths[name] = target
    return paths


def activate(paths: dict[str, str]) -> None:
    """组合根启动时调用一次。"""
    _ACTIVE.clear()
    _ACTIVE.update(paths)


def read_path(name: str, project_root: str) -> str:
    """读的时候用哪个文件：启动时登记的优先，否则回退旧位置。

    回退是为了两类场景：单测/CLI 没有组合根（不该强迫它们建目录），
    以及升级后第一次启动时迁移还没跑。
    """
    active = _ACTIVE.get(name)
    if active:
        return active
    return os.path.join(project_root, LEGACY_SUBDIR, name)


def read_paths(project_root: str) -> dict[str, str]:
    return {name: read_path(name, project_root) for name in RUNTIME_FILES}
