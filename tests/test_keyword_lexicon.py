"""关键词词表指纹：改词表必须是显式动作。

为什么不是「把词表外置成 YAML」：`src/keywords.py` 985 行里只有 36 行（3.7%）
是词表与正则，830 行（84.3%）是抽取与四道闸门的算法。把 36 行搬进配置文件，
换来的是「多一层加载 + 校验 + 回退」，而产品条款本身根本不在这里——
它是 `data/knowledge/*.md`，改它走的是知识库上传与审批，本来就不用发版。

真正要防的是另一件事：改一个停用词，评测可能照样通过，但答案变了。
所以这里给词表拍指纹——任何改动都会让测试失败，必须显式更新基线，
`git diff` 里就能看见「谁动了哪个词」。

更新方式：python tests/test_keyword_lexicon.py --update
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import keywords as kw  # noqa: E402

BASELINE = ROOT / "tests" / "lexicon_baseline.json"
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def digest(value) -> dict:
    """把常量变成可比对的指纹；规则与生成基线时完全一致。"""
    if isinstance(value, re.Pattern):
        payload, kind = {"pattern": value.pattern, "flags": value.flags}, "regex"
    elif isinstance(value, (set, frozenset)):
        payload, kind = sorted(map(str, value)), "set"
    elif isinstance(value, (tuple, list)):
        payload, kind = [str(x) for x in value], "seq"
    elif isinstance(value, dict):
        payload, kind = {str(k): str(v) for k, v in sorted(value.items())}, "dict"
    else:
        payload, kind = str(value), "scalar"
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {"type": kind,
            "size": len(value) if hasattr(value, "__len__") else 1,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]}


def current() -> dict:
    out = {}
    for name in sorted(n for n in dir(kw) if n.isupper() and not n.startswith("__")):
        value = getattr(kw, name)
        if isinstance(value, (int, float, str, bool, re.Pattern, set, tuple, list, dict)):
            out[name] = digest(value)
    return out


def main() -> int:
    update = "--update" in sys.argv
    now = current()
    if update:
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8", newline="")
        print(f"已更新基线：{len(now)} 个常量 → {BASELINE.name}")
        return 0

    check("基线文件存在", BASELINE.is_file(), str(BASELINE))
    if not BASELINE.is_file():
        print("\n首次运行请执行：python tests/test_keyword_lexicon.py --update")
        return 1

    saved = json.loads(BASELINE.read_text(encoding="utf-8"))
    added = sorted(set(now) - set(saved))
    removed = sorted(set(saved) - set(now))
    changed = sorted(n for n in set(now) & set(saved) if now[n] != saved[n])

    print("词表指纹比对")
    check("没有新增常量未登记", not added, "新增: " + "、".join(added))
    check("没有常量被删", not removed, "删除: " + "、".join(removed))
    check("没有常量被改动", not changed,
          "改动: " + "、".join(f"{n}({saved[n]['size']}→{now[n]['size']})" for n in changed))
    check("常量总数一致", len(now) == len(saved), f"{len(saved)} → {len(now)}")

    print("\n关键闸门词表仍在")
    check("否定标记表非空", bool(saved.get("_NEG_MARKERS", {}).get("size")),
          str(saved.get("_NEG_MARKERS")))
    check("解释型意图正则仍在", saved.get("_EXPLAIN", {}).get("type") == "regex")
    check("停用词表非空", bool(saved.get("_STOP", {}).get("size")), str(saved.get("_STOP")))

    if added or removed or changed:
        print("\n词表变了。若是有意改动：")
        print("  1) 跑一遍 python tests/eval_run.py 确认答案质量没退化")
        print("  2) python tests/test_keyword_lexicon.py --update 更新基线")
        print("  3) 在 CHANGELOG 里说明改了什么、为什么")

    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
