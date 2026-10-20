"""极简 Redis 客户端（RESP2），只覆盖限流/幂等/成本需要的命令。

为什么不装 `redis` SDK：本项目运行时零第三方依赖是交付约束之一，而这里只需要
GET / SET NX PX / INCRBY / EXPIRE / EVAL 五个命令。协议本身很简单，自己实现
反而能把「超时、重连、错误分类」写清楚，不依赖 SDK 的默认行为。

连接策略：
- 每线程一条连接（`threading.local`），HTTP 服务是多线程的，避免锁竞争；
- 命令超时 `REDIS_TIMEOUT_S`，连接失败重试 1 次（100ms 退避），仍失败抛
  `RedisError`，由 `guards` 降级到进程内状态并在健康检查里暴露；
- 不做连接池上限：单实例 QPS 由入口限流控制，连接数不会无限增长。
"""
from __future__ import annotations

import socket
import ssl
import threading
import time
from urllib.parse import unquote, urlparse


class RedisError(RuntimeError):
    """连接失败、超时或服务端返回错误。"""


class RedisClient:
    def __init__(self, url: str, timeout_s: float = 1.5, database: int | None = None):
        parsed = urlparse(url)
        if parsed.scheme not in ("redis", "rediss"):
            raise RedisError(f"不支持的 Redis URL scheme: {parsed.scheme or '（空）'}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = int(parsed.port or 6379)
        self.password = unquote(parsed.password) if parsed.password else ""
        self.username = unquote(parsed.username) if parsed.username else ""
        self.db = database if database is not None else int((parsed.path or "/0").strip("/") or 0)
        self.tls = parsed.scheme == "rediss"
        self.timeout_s = max(0.2, float(timeout_s))
        self._local = threading.local()
        self._lock = threading.Lock()
        self._generation = 0

    # ---------- 连接 ----------
    def _connect(self):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            sock.settimeout(self.timeout_s)
        except OSError as exc:
            raise RedisError(f"连接 {self.host}:{self.port} 失败: {exc}") from exc
        if self.tls:
            context = ssl.create_default_context()
            try:
                sock = context.wrap_socket(sock, server_hostname=self.host)
            except (ssl.SSLError, OSError) as exc:
                sock.close()
                raise RedisError(f"TLS 握手失败: {exc}") from exc
        fileobj = sock.makefile("rb")
        state = {"sock": sock, "file": fileobj}
        self._local.state = state
        if self.password:
            args = ["AUTH", self.password]
            if self.username and self.username != "default":
                args = ["AUTH", self.username, self.password]
            self._send(args)
            reply = self._read_reply()
            if isinstance(reply, RedisError):
                raise reply
        if self.db:
            self._send(["SELECT", str(self.db)])
            reply = self._read_reply()
            if isinstance(reply, RedisError):
                raise reply
        return state

    def _state(self):
        state = getattr(self._local, "state", None)
        if state is None:
            state = self._connect()
            with self._lock:
                self._generation += 1
        return state

    def _close(self) -> None:
        state = getattr(self._local, "state", None)
        self._local.state = None
        if not state:
            return
        for key in ("file", "sock"):
            try:
                state[key].close()
            except OSError:
                pass

    # ---------- 协议 ----------
    def _send(self, args) -> None:
        state = self._state()
        parts = [b"*%d\r\n" % len(args)]
        for arg in args:
            if isinstance(arg, bytes):
                raw = arg
            else:
                raw = str(arg).encode("utf-8")
            parts.append(b"$%d\r\n%s\r\n" % (len(raw), raw))
        try:
            state["sock"].sendall(b"".join(parts))
        except OSError as exc:
            raise RedisError(f"写入失败: {exc}") from exc

    def _read_line(self, fileobj) -> bytes:
        line = fileobj.readline()
        if not line:
            raise RedisError("连接被服务端关闭")
        if not line.endswith(b"\r\n"):
            raise RedisError("协议错误：行未以 CRLF 结束")
        return line[:-2]

    def _read_reply(self):
        state = getattr(self._local, "state")
        if not state:
            raise RedisError("未连接")
        fileobj = state["file"]
        try:
            line = self._read_line(fileobj)
        except OSError as exc:
            raise RedisError(f"读取失败: {exc}") from exc
        if not line:
            raise RedisError("空响应")
        prefix, payload = line[:1], line[1:]
        if prefix == b"+":
            return payload.decode("utf-8", "replace")
        if prefix == b"-":
            return RedisError(payload.decode("utf-8", "replace"))
        if prefix == b":":
            return int(payload)
        if prefix == b"$":
            length = int(payload)
            if length < 0:
                return None
            try:
                data = fileobj.read(length + 2)
            except OSError as exc:
                raise RedisError(f"读取 bulk 失败: {exc}") from exc
            return data[:-2].decode("utf-8", "replace")
        if prefix == b"*":
            count = int(payload)
            if count < 0:
                return None
            return [self._read_reply() for _ in range(count)]
        raise RedisError(f"未知响应前缀: {prefix!r}")

    def execute(self, *args):
        """执行一条命令；连接异常时重连并重试一次。"""
        last: Exception | None = None
        for attempt in range(2):
            try:
                self._send(list(args))
                reply = self._read_reply()
                if isinstance(reply, RedisError):
                    raise reply
                return reply
            except RedisError as exc:
                last = exc
                self._close()
                if attempt == 0:
                    time.sleep(0.1)
        raise RedisError(str(last) if last else "Redis 调用失败")

    # ---------- 便捷方法 ----------
    def ping(self) -> bool:
        try:
            return self.execute("PING") == "PONG"
        except RedisError:
            return False

    def get(self, key: str):
        return self.execute("GET", key)

    def set(self, key: str, value: str, ttl_s: int | None = None, nx: bool = False) -> bool:
        args = ["SET", key, value]
        if ttl_s is not None:
            args += ["PX", str(max(1, int(ttl_s * 1000)))]
        if nx:
            args.append("NX")
        return self.execute(*args) is not None

    def delete(self, key: str) -> int:
        return int(self.execute("DEL", key) or 0)

    def incrby(self, key: str, amount: int) -> int:
        return int(self.execute("INCRBY", key, str(int(amount))))

    def expire(self, key: str, ttl_s: int) -> bool:
        return bool(self.execute("EXPIRE", key, str(max(1, int(ttl_s)))))

    def eval(self, script: str, keys: list[str], args: list) -> object:
        return self.execute("EVAL", script, str(len(keys)), *keys, *args)

    def close(self) -> None:
        self._close()
