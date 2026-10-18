"""生成难题集 eval_cases_hard.jsonl —— 用来验证 L3 是否真的有区分力。

基础用例的问题与知识块近乎一一对应，L1/L3 都容易满分，测不出「会不会编、会不会漏、会不会跨文件对齐」。
这里 13 条题按四类难点设计，全部有据可查（答案在 data/knowledge 内）：

- multihop  多跳：需要 2 个以上知识块/文件组合，漏一处就不完整
- numeric   数值边界：易错答（R2 不需要双录、R1 不受测评过期限制）
- conflict  跨文件口径：双录 6 个月 vs 档案 5 年；行内细则允许签不匹配确认书 vs 监管「只能卖等于或低于」
- gap       资料空白：资料没写的东西，正确行为是说"未提供"，而不是编

注意：难题集**不进入发布门禁**（`eval_run.py` 默认只加载 eval_cases.jsonl + 反馈用例），
用于诊断与 L3 校准；要跑它请显式 `--cases tests/eval_cases_hard.jsonl`。

运行：python tests/build_cases_hard.py
"""
import json
from pathlib import Path

HARD_CASES = [
    # ---------- 多跳（4）----------
    {"id": "H01", "category": "multihop",
     "input": "65 周岁以上客户首次购买 R4 理财产品，需要办理哪些手续",
     "expect": {"behavior": "answer", "output_contains": ["特别风险提示"], "retrieval_contains_any": ["特别风险提示", "65 周岁"]},
     "note": "需同时命中：风险测评、R3+ 临柜双录、65 岁特别提示与确认书"},
    {"id": "H02", "category": "multihop",
     "input": "安享系列 5 万元起购，是否符合监管对公募理财产品销售起点的要求",
     "expect": {"behavior": "answer", "output_contains": ["1万元"], "retrieval_contains_any": ["1万元", "销售起点"]},
     "note": "需跨文件：安享起购 5 万元 + 监管第三十条不低于 1 万元，并给出比较结论"},
    {"id": "H03", "category": "multihop",
     "input": "安享 90 天产品到期如何兑付，封闭期内能否提前赎回",
     "expect": {"behavior": "answer", "output_contains": ["一次性兑付"], "retrieval_contains_any": ["一次性兑付", "封闭期"]},
     "note": "一句两问：兑付方式 + 封闭期不可赎回"},
    {"id": "H04", "category": "multihop",
     "input": "私募理财产品的投资冷静期是多久，公募产品是否也有同样要求",
     "expect": {"behavior": "answer", "output_contains": ["24小时"], "retrieval_contains_any": ["24小时", "冷静期"]},
     "note": "私募不少于 24 小时；公募资料未提，答「同样要求」即为编造"},

    # ---------- 数值边界（4）----------
    {"id": "H05", "category": "numeric",
     "input": "首次购买 R2 产品需要双录吗",
     "expect": {"behavior": "answer", "output_contains": ["R3"], "retrieval_contains_any": ["双录", "R3"]},
     "note": "双录只针对 R3 及以上；答「需要」即错"},
    {"id": "H06", "category": "numeric",
     "input": "客户风险测评已过期，想购买 R1 的稳盈系列产品，是否可以",
     "expect": {"behavior": "answer", "output_contains": ["可以购买"], "must_not_leak": ["不可以"], "retrieval_contains_any": ["评估过期", "R1", "谨慎型"]},
     "note": "过期限制只针对 R2 及以上，R1 可买；误答「不可买」即错"},
    {"id": "H07", "category": "numeric",
     "input": "客户投诉一般多久办结，什么情况下可以延长到 30 个工作日",
     "expect": {"behavior": "answer", "output_contains": ["15个工作日"], "retrieval_contains_any": ["15 个工作日", "投诉"]},
     "note": "3 个工作日响应 / 15 个工作日办结 / 多部门复杂投诉 30 个工作日"},
    {"id": "H08", "category": "numeric",
     "input": "公募封闭式理财产品和私募理财产品的净值披露频率分别是多少",
     "expect": {"behavior": "answer", "output_contains": ["每周", "每季度"], "retrieval_contains_any": ["每周", "每季度"]},
     "note": "公募封闭式每周；私募每季度。两个频率必须都对"},

    # ---------- 跨文件口径（3）----------
    {"id": "H09", "category": "conflict",
     "input": "双录资料和销售档案的保存期限分别是多久",
     "expect": {"behavior": "answer", "output_contains": ["6个月", "5年"], "retrieval_contains": ["6 个月", "5 年"]},
     "note": "双录 6 个月（适当性细则）vs 档案 5 年（信息披露办法），不能混成一个"},
    {"id": "H10", "category": "conflict",
     "input": "客户测评结果是 R3，想买 R5 产品，可以买吗，需要什么手续",
     "expect": {"behavior": "answer",
                "output_contains_any": ["不匹配确认书", "风险不匹配", "特别风险提示"],
                "retrieval_contains_any": ["风险不匹配", "风险承受能力等级", "第二十九条"]},
     "note": "监管第二十九条「只能等于或低于」vs 行内细则「可签不匹配确认书」，需讲清张力"},
    {"id": "H11", "category": "conflict",
     "input": "线上渠道销售和临柜销售，风险揭示记录的留存期限是否一致",
     "expect": {"behavior": "answer", "output_contains_any": ["一致", "相同", "同样"], "retrieval_contains_any": ["一致", "留存期限"]},
     "note": "细则第四条：线上电子留痕期限与双录一致"},

    # ---------- 资料空白（2）----------
    {"id": "H12", "category": "gap",
     "input": "稳盈系列的七日年化收益率是多少",
     "expect": {"behavior": "answer",
                "output_contains_any": ["未提供", "未披露", "未找到", "没有", "不含"]},
     "note": "资料只写投资范围与赎回规则，没有具体收益率；编数字即失败"},
    {"id": "H13", "category": "gap",
     "input": "大额存单可以提前支取吗",
     "expect": {"behavior": "answer",
                "output_contains_any": ["未找到", "未明确", "未说明", "没有"]},
     "note": "资料只写支持转让，未写提前支取；答「可以提前支取」即编造"},
]


def main() -> None:
    out = Path(__file__).resolve().parent / "eval_cases_hard.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for c in HARD_CASES:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"已生成 {len(HARD_CASES)} 条难题 → {out}")


if __name__ == "__main__":
    main()
