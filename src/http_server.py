"""限并发的 HTTP 服务器。

为什么单独一层：组合根（handlers/app.py）要用它，而 server.py 又要用组合根，
放在 server.py 里会形成循环导入。
"""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def busy_body(max_workers: int, reason: str = "server_busy") -> bytes:
    """过载时的响应体。

    `reason` 区分两种满载：`too_many_connections` 是连接槽满（大概率是客户端
    只连不发），`server_busy` 是正在处理的请求太多。两者该采取的处置不同——
    前者是客户端/中间设备的问题，后者才是服务忙。
    """
    return ('{"error":"%s","message":"服务繁忙，请稍后重试",'
            '"max_workers":%d}' % (reason, max_workers)).encode("utf-8")


class SlotAwareHandler(BaseHTTPRequestHandler):
    """把并发名额的扣减推迟到「读完请求行」之后。

    为什么不能像原来那样在 accept 阶段扣：TCP 握手完成到客户端发出请求之间
    有一段时间——浏览器预连接、多标签页、卡住的客户端、只连不发的探测。
    accept 就扣名额，等于让这些空闲连接占住并发额度。实测 64 条一个字节都
    没发的连接就能让 `/api/health` 变成 503，而此时 CPU 完全空闲。

    分界点只能是「请求行读到了」：那一刻才说明这次连接真的要干活。
    连接数仍然要限（`BoundedHTTPServer` 的连接槽），但它允许比工作槽多，
    因为空闲连接很便宜——一个线程加一个 socket。
    """

    _worker_held = False

    def parse_request(self) -> bool:  # noqa: D102 —— 覆盖标准库实现，见类说明
        ok = super().parse_request()
        if not ok:
            return False
        acquire = getattr(self.server, "acquire_worker", None)
        if acquire is None:
            # 裸 ThreadingHTTPServer（测试里可能直接用它）：不限并发
            return True
        if not acquire():
            self._send_busy()
            self.close_connection = True
            return False
        self._worker_held = True
        return True

    def handle_one_request(self) -> None:
        # 每个请求都要重新判断持有状态：keep-alive 下同一个连接会走多轮，
        # 上一轮 release 过之后再复用这个标志会重复释放。
        self._worker_held = False
        try:
            super().handle_one_request()
        finally:
            if self._worker_held:
                self._worker_held = False
                try:
                    self.server.release_worker()
                except (AttributeError, ValueError):
                    pass

    def _send_busy(self) -> None:
        """工作槽满时立刻回 503，不开新线程、不排队。

        排队等内核 backlog 的话客户端什么也收不到，30 秒后拿到读取超时——
        运维看到的是「服务挂了」，而真相是「服务忙」。
        """
        note = getattr(self.server, "note_rejected", None)
        if note is not None:
            # 被拒的请求不经过 server 的 _reject_busy，计数要在这里补上，
            # 否则 /metrics 与健康检查里的「繁忙次数」永远是 0。
            note()
        body = busy_body(getattr(self.server, "max_workers", 0))
        try:
            self.send_response(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", "2")
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except OSError:
            # 对端已经走了；这时连日志都是噪音
            pass


class BoundedHTTPServer(ThreadingHTTPServer):
    """限并发的 HTTP 服务。

    为什么要限：`ThreadingHTTPServer` 来一个连接开一个线程。浏览器会预连接，
    SSE 又长占线程，几十个慢客户端就能把线程数打满、让正常请求排不上。
    个人电脑上也一样——一个卡住的标签页足以把服务拖成假死。

    两道名额：

    - **连接槽**（`max_connections`，默认 128）：accept 时扣。管的是「同时开着的
      socket 有多少」，防止 fd/线程被无限占用。
    - **工作槽**（`max_workers`，默认 64）：读到请求行后扣（见 `SlotAwareHandler`）。
      管的是「同时有多少请求在真正占 CPU」。
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, handler, max_workers: int = 64,
                 max_connections: int = 128):
        super().__init__(address, handler)
        self.max_workers = max(1, int(max_workers))
        # 连接槽不能比工作槽小：否则空闲连接会把「正在干活的请求」挤掉
        self.max_connections = max(self.max_workers, int(max_connections))
        self._workers = threading.BoundedSemaphore(self.max_workers)
        self._conns = threading.BoundedSemaphore(self.max_connections)
        # 被拒的请求数。过载时这个数会涨，是「服务还活着但忙」的唯一外部证据。
        # 加锁：`+=` 在 GIL 下也不是原子操作，多线程同时拒绝会少计。
        self._reject_lock = threading.Lock()
        self.rejected_requests = 0
        # 需要在停机时收尾的后台组件（目录监听等）。放这里而不是靠进程退出：
        # 测试会在同一个进程里反复起停服务，线程不回收就会越堆越多。
        self._closers: list = []

    def add_closer(self, closer) -> None:
        self._closers.append(closer)

    def server_close(self) -> None:
        for closer in self._closers:
            try:
                closer()
            except Exception:  # noqa: BLE001 —— 收尾失败不能挡住端口释放
                pass
        self._closers.clear()
        super().server_close()

    def acquire_worker(self) -> bool:
        """占一个工作槽；失败说明当前正在处理的请求已达上限。"""
        return self._workers.acquire(blocking=False)

    def release_worker(self) -> None:
        try:
            self._workers.release()
        except ValueError:
            # 重复释放只会让计数虚高、最终把服务永久锁死，宁可丢掉也不加。
            pass

    def process_request(self, request, client_address):
        if not self._conns.acquire(blocking=False):
            self._reject_busy(request, "too_many_connections")
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._conns.release()
            raise

    def note_rejected(self) -> None:
        """记一次「因为忙而拒绝」。两条拒绝路径（连接槽满、工作槽满）都要走这里。"""
        with self._reject_lock:
            self.rejected_requests += 1

    def _reject_busy(self, request, reason: str = "server_busy") -> None:
        """不开线程、直接回一个 503 再关连接。

        这里手写 HTTP 响应而不是走 handler：handler 跑起来要开线程，
        而「开不出线程」正是当前的处境。报文很短，sendall 不会真正阻塞。
        """
        self.note_rejected()
        body = busy_body(self.max_workers, reason)
        head = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Retry-After: 2\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n"
        )
        try:
            # 先把对端已经发出的请求读掉。不读就关，Windows 会因「接收缓冲区有未读数据」
            # 直接发 RST，客户端拿到的是 ConnectionAborted 而不是这条 503——
            # 拒绝报文写得再好也到不了对端。超时给得很短：过载时不能在 accept 上磨蹭。
            request.settimeout(0.05)
            try:
                request.recv(4096)
            except OSError:
                pass
            request.sendall(head + body)
            # 发完先关写方向再 close，让对端能把数据读完（FIN 而不是 RST）。
            try:
                request.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        except OSError:
            # 客户端已经走了，没必要再管；这时连日志都是噪音。
            pass
        finally:
            try:
                request.close()
            except OSError:
                pass

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conns.release()
