"""解压前的体积闸门：压缩后很小不等于解压后很小。

为什么单独一个模块：`zipfile` 的标准库实现没有解压配额，`read()` 会把整个条目
一次性解进内存。上传口只卡了「压缩后 6 MB」，而一个高压缩比的 XML（大量重复
空白节点）能在 6 MB 内膨胀到几百 MB，几个并发就能把进程吃干。

判据取两条里更严的：
- 所有条目**声明**解压体积之和超过 `MAX_TOTAL` → 拒绝；
- 单条目压缩比超过 `MAX_RATIO`（且解压后 >1 MB，避免小文件误判）→ 拒绝。

只看声明值够不够：`zipfile.read()` 会在解完后校验实际长度与 CRC，
声明小、实际大的包会在这里抛 BadZipFile，不会静默返回超长数据。
"""
from __future__ import annotations

MAX_TOTAL = 64 * 1024 * 1024      # 单个压缩包解压后最多 64 MB
MAX_RATIO = 200                   # 单条目压缩比上限
MIN_CHECK = 1024 * 1024           # 小于 1 MB 的条目不查压缩比


class ZipLimitError(ValueError):
    """解压体积/压缩比超限。"""


def guard(archive, max_total: int | None = None, max_ratio: int | None = None) -> int:
    """检查一个已打开的 ZipFile，超限就抛。返回声明解压总字节数。

    上限走运行时读取（`None` 表示用模块默认），不写成默认参数——
    默认参数在函数定义时就求值了，测试里改模块常量会改不动。
    """
    total_limit = MAX_TOTAL if max_total is None else max_total
    ratio_limit = MAX_RATIO if max_ratio is None else max_ratio
    total = 0
    for info in archive.infolist():
        size = max(0, int(getattr(info, "file_size", 0) or 0))
        total += size
        if total > total_limit:
            raise ZipLimitError(
                f"解压后体积超过上限（{total_limit} 字节），已拒绝")
        packed = max(1, int(getattr(info, "compress_size", 1) or 1))
        if size >= MIN_CHECK and size / packed > ratio_limit:
            raise ZipLimitError(
                f"「{info.filename}」压缩比 {size // packed}:1 异常，已拒绝")
    return total
