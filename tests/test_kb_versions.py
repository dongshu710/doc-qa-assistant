"""知识库版本库 / 审批流 / 文档级回滚测试。

用法：python tests/test_kb_versions.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kbstore import KnowledgeError, KnowledgeStore  # noqa: E402


def seed(tmp: Path) -> Path:
    kb = tmp / "seed"
    kb.mkdir()
    (kb / "a.md").write_text("# A\n\n## 一、额度\n\n额度 100 元。\n", encoding="utf-8")
    (kb / "b.md").write_text("# B\n\n## 一、流程\n\n流程三步。\n", encoding="utf-8")
    return kb


def test_bootstrap(tmp: Path) -> KnowledgeStore:
    store = KnowledgeStore(str(tmp / "kb"), seed_dir=str(seed(tmp)))
    status = store.bootstrap()
    assert status["active"] == "v0001" and status["docs"] == 2, status
    assert sorted(p.name for p in Path(store.active_dir()).iterdir()) == ["a.md", "b.md"]
    # 再调一次是幂等
    assert store.bootstrap()["active"] == "v0001"
    print("bootstrap OK")
    return store


def test_stage_approve(store: KnowledgeStore) -> None:
    staged = store.stage({"c.md": "# C\n\n## 一、说明\n\n新增文档。\n"}, author="alice", note="add c")
    change_id = staged["change"]["change_id"]
    assert store.status()["pending_changes"] == 1
    assert store.active_version() == "v0001"
    assert not (Path(store.active_dir()) / "c.md").exists(), "审批前不能进活动目录"

    approved = store.approve(change_id, approver="bob", note="ok")
    assert approved["version"] == "v0002"
    assert store.active_version() == "v0002"
    assert (Path(store.active_dir()) / "c.md").exists()
    manifest = approved["manifest"]
    assert manifest["parent"] == "v0001" and manifest["approved_by"] == "bob"
    assert manifest["change_id"] == change_id
    assert len(manifest["docs"]) == 3
    print("stage/approve OK")


def test_reject(store: KnowledgeStore) -> None:
    staged = store.stage({"d.md": "# D\n\n内容\n"}, author="alice")
    change_id = staged["change"]["change_id"]
    store.reject(change_id, approver="bob", reason="不需要")
    assert store.status()["pending_changes"] == 0
    assert store.active_version() == "v0002"
    assert not (Path(store.active_dir()) / "d.md").exists()
    print("reject OK")


def test_rollback_doc(store: KnowledgeStore) -> None:
    # 覆盖 a.md，再按文档回滚到 v0001
    staged = store.stage({"a.md": "# A\n\n## 一、额度\n\n额度 999 元。\n"}, author="alice")
    store.approve(staged["change"]["change_id"], approver="bob")
    assert "999" in store.read_doc("a.md").decode("utf-8")

    result = store.rollback_doc("a.md", "v0001", author="carol", note="口径回退")
    assert result["from"] == "v0001"
    content = store.read_doc("a.md").decode("utf-8")
    assert "100 元" in content and "999" not in content
    # 其他文档不受影响：c.md 仍在（v0002 新增）
    assert (Path(store.active_dir()) / "c.md").exists()
    manifest = result["manifest"]
    assert manifest["kind"] == "rollback_doc" and manifest["restored_from"] == "v0001"

    history = store.doc_history("a.md")
    assert len(history) >= 3 and history[-1]["version"] == result["version"]
    print("doc rollback OK")


def test_base_conflict(store: KnowledgeStore) -> None:
    one = store.stage({"e.md": "# E\n\n一\n"}, author="alice")
    two = store.stage({"f.md": "# F\n\n二\n"}, author="alice")
    store.approve(one["change"]["change_id"], approver="bob")
    try:
        store.approve(two["change"]["change_id"], approver="bob")
    except KnowledgeError as exc:
        assert "基于" in str(exc)
        print("base conflict OK")
    else:
        raise AssertionError("过期基线的变更必须被拒绝")


def test_bad_name(store: KnowledgeStore) -> None:
    for bad in ("../x.md", "a/b.md", "x.exe"):
        try:
            store.stage({bad: b"x"}, author="alice")
        except KnowledgeError:
            continue
        raise AssertionError(f"应拒绝非法文件名: {bad}")
    print("name guard OK")


def test_delete(store: KnowledgeStore) -> None:
    before = store.active_version()
    staged = store.stage({}, author="alice", deletes=["b.md"])
    store.approve(staged["change"]["change_id"], approver="bob")
    assert not (Path(store.active_dir()) / "b.md").exists()
    assert store.active_version() != before
    print("delete via change OK")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        store = test_bootstrap(Path(tmp))
        test_stage_approve(store)
        test_reject(store)
        test_rollback_doc(store)
        test_base_conflict(store)
        test_bad_name(store)
        test_delete(store)
    print("ALL KB VERSION TESTS PASSED")
