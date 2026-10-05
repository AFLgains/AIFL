"""Executors run jobs (plain, picklable data) and yield results. LocalPool now; a cloud executor later, same interface."""
from .local import LocalPool, Serial


def make_executor(parallel: int = 8):
    return LocalPool(parallel) if parallel > 1 else Serial()


__all__ = ["LocalPool", "Serial", "make_executor"]
