"""纯标准库 .eml 取文本（零第三方依赖）。

为什么需要：客户沟通里定下的口径（「这笔费率按 0.3% 走」）常常只在邮件里，
而邮件是标准的 MIME 结构，`email` 模块就能解，不需要任何第三方库。

能力边界：
- 支持：主题、发件人、日期、正文（优先 text/plain，没有则转 HTML）、
  多层 multipart 与 base64/quoted-printable 编码、常见中日韩编码。
- 不解析附件内容（只报告有几个），也不展开 `.msg` 老格式（那是另一套 OLE 结构）。
- 邮件正文里的引用历史（`>` 开头、`-----Original Message-----`）会保留：
  同一串沟通里上一封的口径往往就在引用里，删掉比留下更容易丢信息。
"""
from __future__ import annotations

import email
import email.policy
import re
from email import message_from_bytes

from . import html_text

MAX_CHARS = 400_000


class EmlError(RuntimeError):
    pass


def _decode_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        # 声明了不存在的字符集（如 x-unknow-8bit）：退到 utf-8 再退 gb18030，
        # 中文邮件里后者的命中率比 latin-1 高得多。
        try:
            return payload.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return payload.decode("gb18030", errors="replace")


def _walk(message) -> tuple[str, str, int]:
    """返回 (纯文本, HTML, 附件数)。多段时按出现顺序拼接纯文本部分。"""
    texts: list[str] = []
    htmls: list[str] = []
    attachments = 0
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition or part.get_filename():
            attachments += 1
            continue
        kind = part.get_content_type()
        if kind == "text/plain":
            texts.append(_decode_part(part))
        elif kind == "text/html":
            htmls.append(_decode_part(part))
    return "\n\n".join(t for t in texts if t.strip()), "\n\n".join(htmls), attachments


def extract_eml(data: bytes, title: str = "") -> tuple[str, dict]:
    """返回 (Markdown, 统计信息)。"""
    try:
        message = message_from_bytes(data, policy=email.policy.default)
    except Exception as exc:  # noqa: BLE001 —— 结构坏了要明确报，不返回空文档
        raise EmlError(f"邮件解析失败：{type(exc).__name__}") from exc

    subject = str(message.get("Subject") or "").strip() or title.strip() or "邮件"
    sender = str(message.get("From") or "").strip()
    when = str(message.get("Date") or "").strip()
    to = str(message.get("To") or "").strip()

    plain, html, attachments = _walk(message)
    if not plain.strip() and html.strip():
        try:
            plain, _meta = html_text.extract_html(html.encode("utf-8"), subject)
        except html_text.HtmlError:
            plain = re.sub(r"<[^>]+>", " ", html)
    body = plain.strip()
    if not body:
        raise EmlError("这封邮件没有可提取的正文（可能只有附件或纯图片）")

    head = [f"# {subject}", ""]
    for label, value in (("发件人", sender), ("收件人", to), ("日期", when)):
        if value:
            head.append(f"- {label}：{value}")
    if len(head) > 1:
        head.append("")
    md = "\n".join(head) + "\n" + body + "\n"
    if len(md) > MAX_CHARS:
        md = md[:MAX_CHARS]
    return md, {
        "engine": "builtin-eml",
        "chars": len(body),
        "attachments": attachments,
        "subject": subject,
        "truncated": len(md) >= MAX_CHARS,
    }
