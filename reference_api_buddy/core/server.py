"""Threaded HTTP server and handler for Reference API Buddy."""

import threading
from http.server import ThreadingHTTPServer
from logging import getLogger

logger = getLogger(__name__)


class ThreadedHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with connection pooling."""

    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, proxy_instance):
        self.proxy_instance = proxy_instance

        def handler(*args, **kwargs):
            return RequestHandlerClass(*args, proxy_instance=proxy_instance, **kwargs)

        super().__init__(server_address, handler)
        self._run_thread = None

    def start(self, blocking=True):
        if blocking:
            logger.info("Starting server in blocking mode...")
            self.serve_forever()
        else:
            logger.info("Starting server in non-blocking mode...")
            self._run_thread = threading.Thread(target=self.serve_forever, daemon=True)
            self._run_thread.start()
        logger.info("Server started.")

    def stop(self):
        logger.info("Stopping server...")
        self.shutdown()
        self.server_close()
        if self._run_thread:
            self._run_thread.join()
        logger.info("Server stopped.")
