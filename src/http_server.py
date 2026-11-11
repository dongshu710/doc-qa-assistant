"""限并发的 HTTP 服务器。

为什么单独一层：组合根（handlers/app.py）要用它，而 server.py 又要用组合根，
放在 server.py 里会形成循环导入。
"""
from __future__ import annotations

import socket
import threading
from http.server import ThreadingHTTPServer


class BoundedHTTPServer(ThreadingHTTPServer):
    """限并发的 HTTP 服务。

    为什么要限：`ThreadingHTTPServer` 来一个连接开一个线程。浏览器会预连接，
    SSE 又长占线程，几十个慢客户端就能把线程数打满、让正常请求排不上。
    个人电脑上也一样——一个卡住的标签页足以把服务拖成假死。
    """

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, handler, max_workers: int = 64):
        super().__init__(address, handler)
        self.max_workers = max(1, int(max_workers))
        self._slots = threading.BoundedSemaphore(self.max_workers)
        # 被拒的请求数。过载时这个数会涨，是「服务还活着但忙」的唯一外部证据。
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

    def process_request(self, request, client_address):
        # 槽位满时立刻回 503，而不是在 accept 阶段干等内核 backlog。
        # 为什么改掉原来的阻塞等待：等的时候客户端什么也收不到，30 秒后拿到的是
        # 读取超时——运维看到的是「服务挂了」，而真相是「服务忙」。拒绝要说得出来。
        if not self._slots.acquire(blocking=False):
            self._reject_busy(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def _reject_busy(self, request) -> None:
        """不开线程、直接回一个 503 再关连接。

        这里手写 HTTP 响应而不是走 handler：handler 跑起来要开线程，
        而「开不出线程」正是当前的处境。报文很短，sendall 不会真正阻塞。
        """
        self.rejected_requests += 1
        body = ('{"error":"server_busy","message":"服务繁忙，请稍后重试",'
                '"max_workers":%d}' % self.max_workers).encode("utf-8")
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
            self._slots.release()
