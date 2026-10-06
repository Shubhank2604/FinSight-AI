"""Atomic replacement with bounded retries for temporary Windows file locks."""
import os
import time


def atomic_replace(source, target):
    delays = (0.05, 0.1, 0.2, 0.4)
    for attempt in range(len(delays) + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32} or attempt == len(delays):
                raise
            time.sleep(delays[attempt])
