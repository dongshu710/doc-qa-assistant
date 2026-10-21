"""多轮上下文：会话存储的 TTL/轮数上限，以及追问改写是否真的带上了上一轮。"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import RAGPipeline  # noqa: E402
from src.sessions import SessionStore  # noqa: E402


def test_store() -> None:
    store = SessionStore(max_turns=2, ttl_s=60, max_sessions=2)
    store.append("s1", "第一问", "答一")
    store.append("s1", "第二问", "答二")
    store.append("s1", "第三问", "答三")
    history = store.history("s1")
    assert [t.query for t in history] == ["第二问", "第三问"], history

    store.append("s2", "另一个会话", "答")
    store.append("s3", "第三个会话", "答")
    assert store.status()["sessions"] <= 2, store.status()

    store.clear("s1")
    assert not store.history("s1")
    assert store.history(None) == []
    print("session store OK")


def test_followup() -> None:
    root = Path(tempfile.mkdtemp(prefix="sess_"))
    (root / "a.md").write_text(
        "# 产品要求\n\n## 一、R2\n\nR2 产品完成风险测评后即可购买。\n\n"
        "## 二、R3\n\nR3 产品首次购买须在营业网点完成双录。\n",
        encoding="utf-8")
    env = {"RETRIEVAL": "bm25", "MIN_SCORE": "0", "QUERY_EXPANSION": "off",
           "KEYWORD_MODE": "off", "KB_STORE": "off"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        pipe = RAGPipeline(str(root))
        first = pipe.ask("R3 产品首次购买有什么要求", session_id="sess-test")
        assert first["turn"] == 1, first.get("turn")
        assert first.get("context_query") is None, first.get("context_query")

        second = pipe.ask("那 R2 呢", session_id="sess-test")
        assert second["turn"] == 2, second.get("turn")
        assert second["context_query"] and "R3 产品" in second["context_query"], second.get("context_query")
        assert second["query"] == "那 R2 呢"

        # 独立问题不拼上文，避免上一轮把新问题带偏
        third = pipe.ask("大额存单可以转让吗", session_id="sess-test")
        assert third.get("context_query") is None, third.get("context_query")

        # 不传 session 时完全没有上下文
        fresh = pipe.ask("那 R2 呢")
        assert fresh.get("context_query") is None and fresh.get("turn") is None
        assert pipe.sessions.status()["sessions"] == 1, pipe.sessions.status()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("follow-up context OK")


def test_ttl() -> None:
    store = SessionStore(max_turns=3, ttl_s=1)
    store.append("s", "q", "a")
    assert store.history("s")
    time.sleep(1.1)
    assert store.history("s") == []
    print("ttl OK")


def main() -> None:
    test_store()
    test_followup()
    test_ttl()
    print("ALL SESSION TESTS PASSED")


if __name__ == "__main__":
    main()
