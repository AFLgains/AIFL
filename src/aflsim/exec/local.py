"""Run jobs in parallel on this machine. The executor interface is tiny on purpose, so a cloud executor can replace it:

    for result in executor.imap(fn, jobs): ...     # results in COMPLETION order; fn and jobs must be picklable
    results = executor.map(fn, jobs)               # a list in SUBMISSION order (use it when order matters)

A crashed worker (BrokenProcessPool: out of memory, a native crash, the machine sleeping) does not lose the run: the
pool is rebuilt and the unfinished jobs are resubmitted. A job that kills its worker twice is reported as failed
(`on_fail`) and skipped rather than retried forever.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool


class _Ordered:
    def map(self, fn, jobs, on_fail=None, on_error=None) -> list:
        """Like imap, but the results come back as a list in SUBMISSION order (failed jobs are None).
        Use it whenever a statistic depends on the order of the results."""
        jobs = list(jobs); out = [None] * len(jobs)
        tagged = [(i, job) for i, job in enumerate(jobs)]
        for i, res in self.imap(_Indexed(fn), tagged, on_fail=(lambda t, why: on_fail(t[1], why)) if on_fail else None,
                                on_error=(lambda t, e: on_error(t[1], e)) if on_error else None):
            out[i] = res
        return out


class _Indexed:
    """Picklable wrapper: runs fn on the job and returns (index, result)."""

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, tagged):
        i, job = tagged
        return i, self.fn(job)


class Serial(_Ordered):
    """In-process, one job at a time (LLM games, debugging, tests)."""

    def imap(self, fn, jobs, on_fail=None, on_error=None):
        for job in jobs:
            try:
                yield fn(job)
            except Exception as e:                                          # noqa: BLE001
                if on_error is None:
                    raise
                on_error(job, e)


class LocalPool(_Ordered):
    def __init__(self, parallel: int = 8, max_in_flight: int | None = None):
        self.parallel = max(1, int(parallel)); self.max_in_flight = max_in_flight or 4 * self.parallel

    def imap(self, fn, jobs, on_fail=None, on_error=None):
        """on_fail(job, why): a job crashed its worker twice. on_error(job, exception): a job raised; without it the
        exception propagates (and in-flight jobs are abandoned: a resumable caller simply re-runs)."""
        if self.parallel == 1:
            yield from Serial().imap(fn, jobs, on_error=on_error)
            return
        todo = list(enumerate(jobs)); crashes = {}
        while todo:
            pool = ProcessPoolExecutor(max_workers=self.parallel)
            pending = {}; broken = False
            try:
                while (todo or pending) and not broken:
                    while todo and len(pending) < self.max_in_flight:
                        i, job = todo.pop(0)
                        pending[pool.submit(fn, job)] = (i, job)
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in done:
                        i, job = pending.pop(fut)
                        try:
                            res = fut.result()
                        except BrokenProcessPool:
                            broken = True
                            crashes[i] = crashes.get(i, 0) + 1
                            if crashes[i] >= 2:
                                if on_fail:
                                    on_fail(job, "worker crashed twice on this job")
                            else:
                                todo.insert(0, (i, job))
                            continue
                        except Exception as e:                              # noqa: BLE001
                            if on_error is None:
                                raise
                            on_error(job, e); continue
                        yield res
                if broken:                                                  # every other in-flight job is lost with the pool: redo them
                    for fut, (i, job) in pending.items():
                        todo.insert(0, (i, job))
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
