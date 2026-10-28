"""限并发的 HTTP 服务器。

为什么单独一层：组合根（handlers/app.py）要用它，而 server.py 又要用组合根，
放在 server.py 里会形成循环导入。
"""
from __future__ import annotations

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

    def process_request(self, request, client_address):
        # 拿不到槽位就在 accept 阶段等，让内核 backlog 兜住，而不是无限开线程
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()
