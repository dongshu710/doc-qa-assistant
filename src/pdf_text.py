"""纯标准库 PDF 取文本（零第三方依赖）。

为什么需要它：Web 端要支持「上传 PDF 直接用」，而运行时 Python 里没有 pypdf
（pypdf 只装在 .venv 里做离线预处理）。为了不把「零依赖」这条设计承诺破掉，
这里自己解 PDF：解析对象 → 解 Flate 流 → 读 ToUnicode CMap → 按文本算子还原。

能力边界（写清楚比假装全能重要）：
- 支持：经典 xref 与 xref 流、对象流(/ObjStm)、FlateDecode/ASCIIHex/ASCII85、
  Type0(CID, Identity-H) + ToUnicode、简单字体(WinAnsi/MacRoman)。
- 不支持：扫描件（图片页，无文本层）→ 提取字数极少，由上层提示需要 OCR；
  加密 PDF（/Encrypt）→ 直接报错，不尝试破解。
- 复杂排版（多栏、表格线、旋转）只做行级还原，不还原表格结构。
"""
from __future__ import annotations

import re
import zlib

_WS = b"\x00\t\n\x0c\r "
_DELIM = b"()<>[]{}/%"


class PDFError(RuntimeError):
    pass


# ---------------------------------------------------------------- 对象解析
class _Obj:
    __slots__ = ("num", "body", "stream", "decoded")

    def __init__(self, num: int, body: bytes, stream: bytes | None):
        self.num = num
        self.body = body
        self.stream = stream
        self.decoded: bytes | None = None


def _find_stream_range(data: bytes, after: int, limit: int) -> tuple[int, int] | None:
    """定位 `stream` 与 `endstream` 之间的字节区间（不含分隔换行）。"""
    m = re.compile(rb"(?<![A-Za-z])stream(?:\r\n|\n|\r)").search(data, after, limit)
    if not m:
        return None
    start = m.end()
    end = data.find(b"endstream", start, limit)
    if end < 0:
        return None
    # 去掉 endstream 前的 EOL
    while end > start and data[end - 1:end] in (b"\n", b"\r"):
        end -= 1
    return start, end


_OBJ_RE = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")


def _parse_objects(data: bytes) -> dict[int, _Obj]:
    """顺序扫描对象，**跳过流内部**。

    为什么要手动推进游标而不是 `finditer` 全文件匹配：字体文件等二进制流里
    很可能恰好出现 `12 0 obj` 这样的字节序列，一旦被当成对象解析，
    就会覆盖同号真对象、把后续内容切错。
    """
    objs: dict[int, _Obj] = {}
    pos = 0
    while True:
        m = _OBJ_RE.search(data, pos)
        if not m:
            break
        num = int(m.group(1))
        start = m.end()
        endobj = data.find(b"endobj", start)
        limit = endobj if endobj > 0 else len(data)
        rng = _find_stream_range(data, start, limit + 9)
        if rng:
            s_start, s_end = rng
            objs[num] = _Obj(num, data[start:s_start], data[s_start:s_end])
            endstream = data.find(b"endstream", s_end)
            after = data.find(b"endobj", endstream) if endstream > 0 else -1
            pos = (after + 6) if after > 0 else (endstream + 9 if endstream > 0 else len(data))
        else:
            objs[num] = _Obj(num, data[start:limit], None)
            pos = (endobj + 6) if endobj > 0 else len(data)
    return objs


def _ref(body: bytes, key: bytes) -> int | None:
    """取 `/Key 12 0 R` 里的对象号。"""
    m = re.search(rb"/" + key + rb"\s+(\d+)\s+\d+\s+R", body)
    return int(m.group(1)) if m else None


def _name(body: bytes, key: bytes) -> str | None:
    m = re.search(rb"/" + key + rb"\s*/([A-Za-z0-9#._+-]+)", body)
    return m.group(1).decode("latin-1") if m else None


def _dict_slice(body: bytes, key: bytes) -> bytes | None:
    """取 `/Key << ... >>` 的字典片段（按括号配平，支持嵌套）。"""
    m = re.search(rb"/" + key + rb"\s*<<", body)
    if not m:
        return None
    i = m.end() - 2
    depth = 0
    while i < len(body):
        if body[i:i + 2] == b"<<":
            depth += 1
            i += 2
            continue
        if body[i:i + 2] == b">>":
            depth -= 1
            i += 2
            if depth == 0:
                return body[m.end() - 2:i]
            continue
        i += 1
    return None


def _ascii85(raw: bytes) -> bytes:
    raw = re.sub(rb"\s", b"", raw)
    if raw.startswith(b"<~"):
        raw = raw[2:]
    if raw.endswith(b"~>"):
        raw = raw[:-2]
    out = bytearray()
    group: list[int] = []
    for ch in raw:
        if ch == 0x7A and not group:  # 'z' → 4 个 0 字节
            out += b"\x00\x00\x00\x00"
            continue
        if ch < 33 or ch > 117:
            continue
        group.append(ch - 33)
        if len(group) == 5:
            n = 0
            for g in group:
                n = n * 85 + g
            out += n.to_bytes(4, "big")
            group = []
    if group:
        pad = 5 - len(group)
        n = 0
        for g in group + [84] * pad:
            n = n * 85 + g
        out += n.to_bytes(4, "big")[:4 - pad]
    return bytes(out)


def _decode_stream(obj: _Obj, objs: dict[int, _Obj]) -> bytes:
    if obj.stream is None:
        return b""
    if obj.decoded is not None:
        return obj.decoded

    body = obj.body
    m = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", body)
    filters: list[str] = []
    if m:
        filters = [x.decode("latin-1") for x in re.findall(rb"/(\w+)", m.group(1))]

    raw = obj.stream
    for f in filters:
        if f in ("FlateDecode", "Fl"):
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                try:  # 有些文件是裸 deflate（无 zlib 头）
                    raw = zlib.decompressobj(-15).decompress(raw)
                except zlib.error as exc:
                    raise PDFError(f"对象 {obj.num} 的 Flate 流解压失败：{exc}") from exc
            # 图像类流可能带 PNG 预测器，文本流一般没有；这里不做预测器反演
        elif f in ("ASCIIHexDecode", "AHx"):
            hexed = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
            if len(hexed) % 2:
                hexed += b"0"
            raw = bytes.fromhex(hexed.decode("ascii"))
        elif f in ("ASCII85Decode", "A85"):
            raw = _ascii85(raw)
        else:
            raise PDFError(f"不支持的流过滤器：/{f}")
    obj.decoded = raw
    return raw


def _expand_objstm(objs: dict[int, _Obj]) -> None:
    """把 /ObjStm 里的压缩对象解出来（Word/Chrome 导出的 PDF 常见）。"""
    for obj in list(objs.values()):
        if not re.search(rb"/Type\s*/ObjStm", obj.body):
            continue
        try:
            data = _decode_stream(obj, objs)
        except PDFError:
            continue
        m = re.search(rb"/N\s+(\d+)", obj.body)
        first_m = re.search(rb"/First\s+(\d+)", obj.body)
        if not m or not first_m:
            continue
        n, first = int(m.group(1)), int(first_m.group(1))
        header = data[:first].split()
        for i in range(0, min(len(header), n * 2), 2):
            try:
                num, off = int(header[i]), int(header[i + 1])
            except (ValueError, IndexError):
                continue
            if num in objs:
                continue
            nxt = len(data)
            if i + 3 < len(header):
                try:
                    nxt = first + int(header[i + 3])
                except (ValueError, IndexError):
                    pass
            objs[num] = _Obj(num, data[first + off:nxt], None)


# ---------------------------------------------------------------- CMap
def _cmap_map(cmap: bytes) -> tuple[dict[int, str], dict[int, int]]:
    """解析 ToUnicode CMap，返回 ({码: 字符}, {码长度: 1})。"""
    mapping: dict[int, str] = {}
    lengths: dict[int, int] = {}
    text = cmap.decode("latin-1", "ignore")

    for block in re.findall(r"begincodespacerange(.*?)endcodespacerange", text, re.S):
        for lo, _hi in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            lengths[len(lo) // 2] = 1

    def _u(h: str) -> str:
        b = bytes.fromhex(h if len(h) % 2 == 0 else h + "0")
        try:
            return b.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[int(src, 16)] = _u(dst)

    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        # 数组形式：<lo> <hi> [<d1> <d2> ...]
        for lo, hi, arr in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S
        ):
            start, end = int(lo, 16), int(hi, 16)
            dsts = re.findall(r"<([0-9A-Fa-f]*)>", arr)
            for i, dst in enumerate(dsts):
                if start + i > end:
                    break
                mapping[start + i] = _u(dst)
        # 连续形式：<lo> <hi> <dst 起始>
        for lo, hi, dst in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block
        ):
            start, end = int(lo, 16), int(hi, 16)
            if end - start > 65535:
                continue
            base = bytes.fromhex(dst if len(dst) % 2 == 0 else dst + "0")
            if not base:
                continue
            prefix, last = base[:-2], int.from_bytes(base[-2:], "big")
            for i in range(end - start + 1):
                val = prefix + ((last + i) & 0xFFFF).to_bytes(2, "big")
                try:
                    mapping[start + i] = val.decode("utf-16-be")
                except UnicodeDecodeError:
                    mapping[start + i] = ""
    return mapping, lengths


class _Font:
    """一个字体：负责把内容流里的字节串还原成 unicode。"""

    def __init__(self, name: str, mapping: dict[int, str], widths: dict[int, int],
                 two_byte: bool, identity: bool):
        self.name = name
        self.mapping = mapping
        self.widths = widths
        self.two_byte = two_byte
        self.identity = identity
        self.unmapped = 0
        self.total = 0

    def decode(self, raw: bytes) -> str:
        if not raw:
            return ""
        if not self.mapping:
            if self.identity:  # Identity-H 但没有 ToUnicode：只能赌 CID==Unicode
                try:
                    out = raw.decode("utf-16-be", "ignore")
                    self.total += len(out)
                    return out
                except Exception:  # noqa: BLE001
                    return ""
            out = raw.decode("latin-1", "ignore")
            self.total += len(out)
            return out

        widths = self.widths or ({2: 1} if self.two_byte else {1: 1})
        step = max(widths) if widths else 2
        out: list[str] = []
        i = 0
        while i < len(raw):
            size = step
            if step == 2 and i + 1 >= len(raw):
                break
            code = int.from_bytes(raw[i:i + size], "big")
            ch = self.mapping.get(code)
            self.total += 1
            if ch is None:
                # 逐级退让：2 字节不行就试 1 字节
                if size == 2:
                    code = raw[i]
                    ch = self.mapping.get(code)
                    size = 1
                if ch is None:
                    self.unmapped += 1
                    i += size
                    continue
            out.append(ch)
            i += size
        return "".join(out)


def _font_from(objs: dict[int, _Obj], num: int) -> _Font | None:
    obj = objs.get(num)
    if not obj:
        return None
    body = obj.body

    mapping: dict[int, str] = {}
    widths: dict[int, int] = {}
    tu = _ref(body, b"ToUnicode")
    if tu and tu in objs:
        try:
            mapping, widths = _cmap_map(_decode_stream(objs[tu], objs))
        except PDFError:
            mapping, widths = {}, {}

    subtype = _name(body, b"Subtype") or ""
    encoding = _name(body, b"Encoding") or ""
    identity = subtype == "Type0" or encoding.startswith("Identity")
    if not widths:
        widths = {2: 1} if identity else {1: 1}
    return _Font(subtype or "?", mapping, widths, two_byte=identity, identity=identity)


# ---------------------------------------------------------------- 内容流
def _literal_string(data: bytes, i: int) -> tuple[bytes, int]:
    """解析字面量字符串 `(...)`，支持转义与嵌套括号。"""
    assert data[i:i + 1] == b"("
    i += 1
    depth = 1
    out = bytearray()
    n = len(data)
    while i < n:
        ch = data[i:i + 1]
        if ch == b"\\":
            nxt = data[i + 1:i + 2]
            if nxt in b"nrtbf":
                out += {b"n": b"\n", b"r": b"\r", b"t": b"\t",
                        b"b": b"\b", b"f": b"\f"}[nxt]
                i += 2
            elif nxt in b"()\\":
                out += nxt
                i += 2
            elif nxt.isdigit():
                m = re.match(rb"\d{1,3}", data[i + 1:i + 4])
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            elif nxt in (b"\n", b"\r"):
                i += 2
                if nxt == b"\r" and data[i:i + 1] == b"\n":
                    i += 1
            else:
                out += nxt
                i += 2
            continue
        if ch == b"(":
            depth += 1
            out += ch
            i += 1
            continue
        if ch == b")":
            depth -= 1
            i += 1
            if depth == 0:
                break
            out += ch
            continue
        out += ch
        i += 1
    return bytes(out), i


def _hex_string(data: bytes, i: int) -> tuple[bytes, int]:
    end = data.find(b">", i)
    if end < 0:
        return b"", len(data)
    hexed = re.sub(rb"[^0-9A-Fa-f]", b"", data[i + 1:end])
    if len(hexed) % 2:
        hexed += b"0"
    return bytes.fromhex(hexed.decode("ascii")), end + 1


def _tokens(data: bytes):
    i, n = 0, len(data)
    while i < n:
        c = data[i:i + 1]
        if c in (b" ", b"\n", b"\r", b"\t", b"\x0c", b"\x00"):
            i += 1
            continue
        if c == b"%":
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == b"(":
            s, i = _literal_string(data, i)
            yield "str", s
            continue
        if c == b"<":
            if data[i:i + 2] == b"<<":
                yield "dict", b""
                i += 2
                continue
            s, i = _hex_string(data, i)
            yield "str", s
            continue
        if c == b">":
            i += 2 if data[i:i + 2] == b">" else 1
            continue
        if c in b"[]{}":
            yield c.decode(), b""
            i += 1
            continue
        if c == b"/":
            j = i + 1
            while j < n and data[j:j + 1] not in _WS and data[j:j + 1] not in _DELIM:
                j += 1
            yield "name", data[i + 1:j]
            i = j
            continue
        j = i
        while j < n and data[j:j + 1] not in _WS and data[j:j + 1] not in _DELIM:
            j += 1
        tok = data[i:j]
        i = j
        try:
            yield "num", float(tok)
        except ValueError:
            yield "op", tok


def _page_content(objs: dict[int, _Obj], page: _Obj) -> bytes:
    """拼一个页面的内容流（/Contents 可能是单引用或数组）。"""
    nums: list[int] = []
    m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page.body)
    if m:
        nums.append(int(m.group(1)))
    else:
        arr = re.search(rb"/Contents\s*\[([^\]]*)\]", page.body)
        if arr:
            nums += [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", arr.group(1))]
    out = bytearray()
    for num in nums:
        obj = objs.get(num)
        if obj:
            try:
                out += _decode_stream(obj, objs)
            except PDFError:
                continue
            out += b"\n"
    return bytes(out)


def _resolve_dict(objs: dict[int, _Obj], body: bytes, key: bytes, depth: int = 0) -> bytes | None:
    """取 /Key 对应的字典：内联 `<<...>>` 或间接引用 `N 0 R`（可再套一层）。"""
    if depth > 4 or not body:
        return None
    inline = _dict_slice(body, key)
    if inline:
        return inline
    ref = _ref(body, key)
    if ref and ref in objs:
        target = objs[ref].body.strip()
        if target.startswith(b"<<"):
            return target
        return _resolve_dict(objs, target, key, depth + 1)
    return None


def _page_fonts(objs: dict[int, _Obj], resources: bytes | None) -> dict[str, _Font]:
    fonts: dict[str, _Font] = {}
    if not resources:
        return fonts
    fonts_dict = _resolve_dict(objs, resources, b"Font")
    if not fonts_dict:
        return fonts
    for name, num in re.findall(rb"/([A-Za-z0-9#._+-]+)\s+(\d+)\s+\d+\s+R", fonts_dict):
        f = _font_from(objs, int(num))
        if f:
            fonts[str(name, "latin-1")] = f
    return fonts


def _est_width(text: str, size: float) -> float:
    """粗略估计一段文字的宽度：CJK 按 1em，ASCII 按 0.5em。只用于判断要不要补空格。"""
    w = 0.0
    for ch in text:
        w += size * (0.5 if ord(ch) < 0x2E80 else 1.0)
    return w


def _extract_page(content: bytes, fonts: dict[str, _Font]) -> str:
    """按文本算子还原一页文字。

    两遍处理：先收集 (y, x, 文本) 片段，再按 y 变化拼行。
    为什么要两遍：段间距只能相对「本页常规行距」判断，硬编码 1.7 倍会把
    自动换行的长句拆成两段（实测把「…监管要求」拆成「监管要 / 求」）。
    """
    segs: list[tuple[float, float, float, str]] = []  # (y, x, size, text)
    font = _Font("?", {}, {1: 1}, False, False)
    size = 12.0
    x = y = 0.0
    leading = 0.0
    operands: list[tuple[str, object]] = []

    def flush_text(raw_text: str) -> None:
        text = font.decode(raw_text)
        if text:
            segs.append((y, x, size, text))

    for kind, val in _tokens(content):
        if kind == "num":
            operands.append(("num", val))
            continue
        if kind in ("str", "name"):
            operands.append((kind, val))
            continue
        if kind != "op":
            continue

        op, args, operands = val, operands, []

        if op == b"BT":
            x = y = 0.0
        elif op == b"Tf":
            names = [a[1] for a in args if a[0] == "name"]
            nums = [a[1] for a in args if a[0] == "num"]
            if names:
                key = names[0].decode("latin-1") if isinstance(names[0], bytes) else str(names[0])
                font = fonts.get(key, font)
            if nums:
                size = float(nums[0]) or size
        elif op in (b"Td", b"TD"):
            nums = [float(a[1]) for a in args if a[0] == "num"]
            if len(nums) >= 2:
                if op == b"TD":
                    leading = -nums[1]
                x += nums[0]
                y += nums[1]
        elif op == b"Tm":
            nums = [float(a[1]) for a in args if a[0] == "num"]
            if len(nums) >= 6:
                x, y = nums[4], nums[5]
        elif op == b"TL":
            nums = [float(a[1]) for a in args if a[0] == "num"]
            if nums:
                leading = nums[0]
        elif op == b"T*":
            y -= leading or size * 1.2
        elif op in (b"Tj", b"'", b'"'):
            if op in (b"'", b'"'):
                y -= leading or size * 1.2
            for k, v in args:
                if k == "str":
                    flush_text(v)
        elif op == b"TJ":
            for k, v in args:
                if k == "str":
                    flush_text(v)
                elif k == "num" and float(v) < -120 and segs:
                    py, px, psize, ptext = segs[-1]
                    segs[-1] = (py, px, psize, ptext + " ")

    if not segs:
        return ""

    gaps = [abs(segs[i - 1][0] - segs[i][0]) for i in range(1, len(segs))
            if abs(segs[i - 1][0] - segs[i][0]) > 0.5]
    median = sorted(gaps)[len(gaps) // 2] if gaps else 0.0

    lines: list[str] = []
    cur: list[str] = []
    prev_y = prev_x = None
    prev_size, prev_text = 12.0, ""
    for sy, sx, ssize, stext in segs:
        if prev_y is None:
            cur.append(stext)
        elif abs(sy - prev_y) <= 0.5:
            if sx - (prev_x + _est_width(prev_text, prev_size)) > max(1.5, prev_size * 0.25):
                cur.append(" ")
            cur.append(stext)
        else:
            lines.append("".join(cur).strip())
            if median and abs(prev_y - sy) > median * 1.55:
                lines.append("")
            cur = [stext]
        prev_y, prev_x, prev_size, prev_text = sy, sx, ssize, stext
    if cur:
        lines.append("".join(cur).strip())

    text = "\n".join(lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_list(objs: dict[int, _Obj]) -> list[tuple[_Obj, bytes | None]]:
    """按页树顺序取页面（含继承的 Resources）；页树坏了就退化为按对象号排序。"""
    root = None
    for obj in objs.values():
        if re.search(rb"/Type\s*/Catalog", obj.body):
            root = _ref(obj.body, b"Pages")
            break

    pages: list[tuple[_Obj, bytes | None]] = []
    seen: set[int] = set()

    def walk(num: int, inherited: bytes | None, depth: int = 0) -> None:
        if depth > 40 or num in seen:
            return
        seen.add(num)
        obj = objs.get(num)
        if not obj:
            return
        own = _resolve_dict(objs, obj.body, b"Resources")
        res = own or inherited
        if re.search(rb"/Type\s*/Pages\b", obj.body):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", obj.body, re.S)
            if kids:
                for kid in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1)):
                    walk(int(kid), res, depth + 1)
        elif re.search(rb"/Type\s*/Page\b", obj.body):
            pages.append((obj, res))

    if root:
        walk(root, None)
    if not pages:
        for o in sorted(objs.values(), key=lambda x: x.num):
            if re.search(rb"/Type\s*/Page\b", o.body):
                pages.append((o, _resolve_dict(objs, o.body, b"Resources")))
    return pages


def extract_text(data: bytes) -> tuple[str, dict]:
    """从 PDF 字节取文本。返回 (文本, 统计信息)。"""
    if not data.startswith(b"%PDF"):
        raise PDFError("不是 PDF 文件（缺少 %PDF 头）")
    # /Encrypt 通常在文件尾部 trailer 里，不能只看开头；用「引用或字典」限定，避免正文误判
    if re.search(rb"/Encrypt\s*(?:\d+\s+\d+\s+R|<<)", data):
        raise PDFError("PDF 已加密，暂不支持（请先解除密码保护再上传）")

    objs = _parse_objects(data)
    if not objs:
        raise PDFError("未解析到任何 PDF 对象，文件可能损坏")
    _expand_objstm(objs)

    pages = _page_list(objs)
    texts: list[str] = []
    fonts_all: dict[str, _Font] = {}
    for page, resources in pages:
        fonts = _page_fonts(objs, resources)
        fonts_all.update(fonts)
        text = _extract_page(_page_content(objs, page), fonts)
        if text:
            texts.append(text)

    joined = "\n\n".join(texts)
    unmapped = sum(f.unmapped for f in fonts_all.values())
    total = sum(f.total for f in fonts_all.values()) or 1
    return joined, {
        "engine": "builtin",
        "pages": len(pages),
        "chars": len(joined),
        "fonts": len(fonts_all),
        "unmapped_ratio": round(unmapped / total, 3),
    }
