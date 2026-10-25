"""应用 profile：把「领域」从代码里抽出来。

同一个 RAG 引擎，两个 profile：
- generic（通用文档问答）：只保留注入/越权/隐私这类**通用安全**护栏；
- finance（金融产品问答）：在通用护栏之上，额外拒绝荐股、收益承诺等金融合规红线。

切换方式：环境变量 `APP_PROFILE=generic|finance`。
默认 finance —— 因为当前知识库就是金融制度与产品说明；换成自己的文档时设 generic。
"""
from dataclasses import dataclass

BASE_REFUSE = [
    r"忽略(以上|之前|上面|前面).*(指令|提示)",
    r"输出.*(系统提示|system\s*prompt)",
    r"ignore\s+(all\s+)?(previous|above)\s+instructions",
    r"print\s+the\s+system\s*prompt",
    r"你现在是.*(管理员|超级用户)",
    r"无需(确认|审核).*(执行|删除|导出)",
    r"(其他|别人).*客户.*(手机号|身份证|卡号)",
]

FINANCE_REFUSE = [
    r"(必涨|稳赚|包赚|翻倍)",
    r"(推荐|买|选).{0,8}(股票|个股)",
]

FINANCE_PROMPT = (
    "你是银行金融产品问答助手。只能依据【资料】回答，禁止编造。\n"
    "规则：\n"
    "1) 每个结论后用 [n] 标注来源编号；\n"
    "2) 资料不足时直接回答「资料中未找到」，不要猜测；\n"
    "3) 金额、利率、风险等级必须精确，不得臆测或四舍五入；\n"
    "4) 不提供投资建议，不做收益承诺。"
)

GENERIC_PROMPT = (
    "你是「记忆文档」，只能依据【资料】回答问题，禁止编造。\n"
    "规则：\n"
    "1) 每个结论后用 [n] 标注来源编号；\n"
    "2) 资料不足时直接回答「资料中未找到」，不要猜测；\n"
    "3) 数字、日期、专有名词必须与资料一致，不得改写或四舍五入；\n"
    "4) 不回答与资料无关的问题。"
)


@dataclass(frozen=True)
class Profile:
    key: str
    app_name: str
    topic_label: str
    system_prompt: str
    extra_refuse: list[str]


PROFILES: dict[str, Profile] = {
    "finance": Profile(
        key="finance",
        app_name="记忆文档",
        topic_label="金融理财",
        system_prompt=FINANCE_PROMPT,
        extra_refuse=FINANCE_REFUSE,
    ),
    "generic": Profile(
        key="generic",
        app_name="记忆文档",
        topic_label="通用文档",
        system_prompt=GENERIC_PROMPT,
        extra_refuse=[],
    ),
}

DEFAULT_PROFILE = "finance"


def get_profile(key: str | None) -> Profile:
    return PROFILES.get((key or "").strip().lower(), PROFILES[DEFAULT_PROFILE])


def refuse_patterns(profile: Profile) -> list[str]:
    return BASE_REFUSE + profile.extra_refuse
