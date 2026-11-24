"""Shared helpers for tests."""

import socket


def free_port() -> int:
    """Return a TCP port on 127.0.0.1 that is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
