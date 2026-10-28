"""分块：重叠只在「超长条款被句号切开」时生效，且必须让缓存失效。

两个容易踩的坑，这里各锁一条：
1. 按「第X条」切出来的块本身是完整条款，再加重叠只会让相邻块互相污染分数；
   只有超长条款被句号强行切开的地方才需要带上下文。
2. 增量缓存原来只认 (mtime, size)，改了 `CHUNK_OVERLAP` 但文件没动时会静默
   复用旧分块——「改了配置没生效」比报错难查得多。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus, parse_document  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


LONG = ("第一条 " + "稳盈系列由本行发行，风险等级为 R2。该产品起购金额为 1 元，追加金额为 100 元。" * 6
        + "该产品的期限为 90 天，业绩比较基准为 3.5%。上述期限自成立日起算，遇节假日顺延。" * 5)
SHORT = "# 说明\n\n## 期限\n\n第一条 稳盈系列起购金额为 1 元，期限 90 天。\n"


def test_default_off() -> None:
    print("默认不重叠（现有语料行为不变）")
    plain = parse_document(SHORT, "a.md")
    with_overlap = parse_document(SHORT, "a.md", 320, 60)
    check("短条款切成 1 块", len(plain) == 1, str(len(plain)))
    check("短条款加重叠也不变", [c.text for c in plain] == [c.text for c in with_overlap])
    check("默认参数就是 0", len(parse_document(LONG, "b.md")) == len(parse_document(LONG, "b.md", 320, 0)))


def test_overlap_applies_to_long_clause() -> None:
    print("超长条款才叠加")
    base = parse_document(LONG, "b.md", 320, 0)
    over = parse_document(LONG, "b.md", 320, 60)
    check("超长条款被切成多块", len(base) >= 2, str(len(base)))
    check("块数不变（重叠不增加块数）", len(base) == len(over), f"{len(base)} vs {len(over)}")
    if len(base) >= 2:
        check("开了重叠后第二块更长", len(over[1].text) > len(base[1].text),
              f"{len(base[1].text)} vs {len(over[1].text)}")
        check("第二块开头带上了前一块的尾巴",
              over[1].text[:12] in base[0].text, over[1].text[:24])
        check("关闭时第二块从新句子起", over[1].text != base[1].text)


def test_overlap_capped() -> None:
    print("重叠不能吃掉整块")
    # 传一个比 max_chars 还大的重叠值，仍应产出正常块
    chunks = parse_document(LONG, "c.md", 320, 999)
    check("仍能切出多块", len(chunks) >= 2, str(len(chunks)))
    check("没有空块", all(c.text.strip() for c in chunks))
    check("超过上限时按 max_chars/4 截断",
          all(len(c.text) <= 320 + 320 // 4 + 40 for c in chunks),
          str([len(c.text) for c in chunks]))


def test_cache_signature() -> None:
    print("改重叠必须让缓存失效")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "d.md").write_text(LONG, encoding="utf-8")
        cache: dict = {}
        first = load_corpus(tmp, cache=cache)
        check("首次解析入缓存", len(cache) == 1, str(len(cache)))
        again = load_corpus(tmp, cache=cache)      # 同样参数：应命中缓存
        check("同参数复用缓存", [c.text for c in first] == [c.text for c in again])
        changed = load_corpus(tmp, cache=cache, overlap=60)
        check("换 overlap 后块变了", [c.text for c in changed] != [c.text for c in first])
        check("缓存被刷新而不是复用旧块", len(changed[1].text) > len(first[1].text),
              f"{len(first[1].text)} vs {len(changed[1].text)}")


def test_env_switch() -> None:
    print("环境变量开关")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "d.md").write_text(LONG, encoding="utf-8")
        old = os.environ.get("CHUNK_OVERLAP")
        try:
            os.environ["CHUNK_OVERLAP"] = "60"
            chunks = load_corpus(tmp)
            check("CHUNK_OVERLAP 生效", len(chunks[1].text) > 200, str(len(chunks[1].text)))
            os.environ["CHUNK_OVERLAP"] = "坏值"
            chunks = load_corpus(tmp)
            check("坏值回退为 0 而不是崩", len(chunks) >= 2)
        finally:
            if old is None:
                os.environ.pop("CHUNK_OVERLAP", None)
            else:
                os.environ["CHUNK_OVERLAP"] = old


def main() -> int:
    test_default_off()
    test_overlap_applies_to_long_clause()
    test_overlap_capped()
    test_cache_signature()
    test_env_switch()
    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
