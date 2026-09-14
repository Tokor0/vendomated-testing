"""Work that takes time: background jobs and a slow-moving sensor.

Real machines do not finish everything the instant you ask.  A restock run has
to wait for the service hatch; the cooling unit takes minutes to pull the
cabinet down to temperature.  This module models both, so the rest of the
library has something genuinely asynchronous in it.

Jobs
----
:class:`JobRunner` accepts work, hands back a job id straight away, and runs
the work on a background thread.  A job moves through
``pending -> running -> succeeded`` or ``-> failed``, and can be cancelled
while it is still pending.  :meth:`JobRunner.get_job` reports where it is;
:meth:`JobRunner.wait_for` blocks until it settles or a timeout expires.

Because a runner owns threads, it should be shut down when you are done with
it -- :meth:`JobRunner.shutdown` waits for the jobs in flight.  It also works
as a context manager.

Sensor
------
:class:`CabinetThermometer` models the cabinet cooling from room temperature
towards its set point at a fixed rate.  It has no thread of its own: every
:meth:`~CabinetThermometer.read` computes the temperature from the elapsed
time, so the reading a caller sees depends on when they ask.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import JobNotFoundError
from .machine import VendingMachine

__all__ = [
    "JobStatus",
    "Job",
    "JobRunner",
    "CabinetThermometer",
]


class JobStatus:
    """The states a job can be in.  Plain strings, so they compare cleanly."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    #: States a job never leaves once it arrives.
    TERMINAL = (SUCCEEDED, FAILED, CANCELLED)


@dataclass
class Job:
    """A unit of background work and whatever became of it.

    :param id: an opaque identifier, unique within the runner.
    :param name: what the job is doing, e.g. ``"restock A1 x3"``.
    :param status: one of the :class:`JobStatus` constants.
    :param result: whatever the work returned, once it has succeeded.
    :param error: the failure message, once it has failed.
    """

    id: str
    name: str
    status: str = JobStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def is_done(self) -> bool:
        """Whether the job has reached a state it will not leave."""
        return self.status in JobStatus.TERMINAL

    def to_dict(self) -> dict:
        """A plain-dict view of the job, safe to serialise to JSON."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobRunner:
    """Runs callables on background threads and tracks how they went.

    :param default_delay: seconds a job waits before it starts doing anything,
        simulating a machine that is not instantaneous.  Individual
        :meth:`submit` calls may override it.
    """

    def __init__(self, default_delay: float = 1.0) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._threads: list[threading.Thread] = []
        self._events: dict[str, threading.Event] = {}
        self.default_delay = float(default_delay)

    def __enter__(self) -> "JobRunner":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()

    def submit(
        self,
        work: Callable[[], Any],
        name: str = "job",
        delay: float | None = None,
    ) -> str:
        """Queue ``work`` and return its job id immediately.

        The call does not block: the job is ``pending`` when this returns, and
        becomes ``running`` once its delay has elapsed.
        """
        job_id = uuid.uuid4().hex[:8]
        wait = self.default_delay if delay is None else float(delay)
        job = Job(id=job_id, name=name)
        finished = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._events[job_id] = finished

        def run() -> None:
            if wait > 0:
                time.sleep(wait)
            with self._lock:
                if job.status == JobStatus.CANCELLED:
                    finished.set()
                    return
                job.status = JobStatus.RUNNING
            try:
                outcome = work()
            except Exception as exc:  # any failure is the job's, not the runner's
                with self._lock:
                    job.status = JobStatus.FAILED
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.finished_at = time.time()
            else:
                with self._lock:
                    job.status = JobStatus.SUCCEEDED
                    job.result = outcome
                    job.finished_at = time.time()
            finally:
                finished.set()

        thread = threading.Thread(target=run, name=f"vendomatic-{job_id}", daemon=True)
        with self._lock:
            self._threads.append(thread)
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> Job:
        """Return the job with this id.

        :raises JobNotFoundError: if the runner has never seen that id.
        """
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError:
                raise JobNotFoundError(f"No such job: {job_id}") from None

    def get_status(self, job_id: str) -> str:
        """Return just the status string of a job."""
        return self.get_job(job_id).status

    def list_jobs(self) -> list[Job]:
        """Every job the runner knows about, oldest first."""
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at)

    def cancel(self, job_id: str) -> bool:
        """Try to cancel a job.

        Returns ``True`` if the job was still pending and is now cancelled,
        ``False`` if it had already started or finished -- cancelling never
        interrupts work that is under way.
        """
        with self._lock:
            job = self.get_job(job_id)
            if job.status != JobStatus.PENDING:
                return False
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
            return True

    def wait_for(self, job_id: str, timeout: float = 10.0) -> Job:
        """Block until a job settles, then return it.

        :raises TimeoutError: if it is still running when ``timeout`` expires.
        """
        with self._lock:
            self.get_job(job_id)  # raises if unknown
            finished = self._events[job_id]
        if not finished.wait(timeout=float(timeout)):
            raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")
        return self.get_job(job_id)

    def shutdown(self, timeout: float = 10.0) -> None:
        """Wait for jobs in flight to finish and forget the threads."""
        with self._lock:
            threads = list(self._threads)
        deadline = time.monotonic() + float(timeout)
        for thread in threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]

    # ---------------------------------------------------- ready-made jobs

    def schedule_restock(
        self,
        machine: VendingMachine,
        code: str,
        quantity: int,
        pin: str,
        delay: float | None = None,
    ) -> str:
        """Queue a restock of ``code`` and return the job id.

        The job unlocks the machine with ``pin``, restocks, and locks it again;
        a wrong PIN, an unknown slot or a slot without room makes the job
        ``failed``, with the reason in :attr:`Job.error`.  The job's result is
        the slot's new quantity.
        """

        def work() -> int:
            machine.unlock(pin)
            try:
                slot = machine.restock(code, quantity)
                return slot.quantity
            finally:
                machine.lock()

        return self.submit(work, name=f"restock {code} x{quantity}", delay=delay)

    def schedule_cash_collection(
        self,
        machine: VendingMachine,
        pin: str,
        delay: float | None = None,
    ) -> str:
        """Queue emptying the coin bank and return the job id.

        The job's result is the coin purse that was collected, with string
        keys so it survives a trip through JSON.
        """

        def work() -> dict[str, int]:
            machine.unlock(pin)
            try:
                return {str(coin): count for coin, count in machine.collect_cash().items()}
            finally:
                machine.lock()

        return self.submit(work, name="collect cash", delay=delay)


class CabinetThermometer:
    """A cooled cabinet that takes its time getting cold.

    The reading starts at ``start_celsius`` and falls towards ``target_celsius``
    at ``rate_celsius_per_second``, computed fresh on every :meth:`read`.  Once
    it reaches the target it stays there.

    :param target_celsius: the set point the cabinet is cooling towards.
    :param start_celsius: the temperature at power-on.
    :param rate_celsius_per_second: how fast it cools.
    :param clock: a zero-argument callable returning seconds, for a
        predictable passage of time; defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        target_celsius: float = 4.0,
        start_celsius: float = 21.0,
        rate_celsius_per_second: float = 2.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if rate_celsius_per_second <= 0:
            raise ValueError("Cooling rate must be positive")
        self.target_celsius = float(target_celsius)
        self.start_celsius = float(start_celsius)
        self.rate = float(rate_celsius_per_second)
        self._clock = clock or time.monotonic
        self._started_at = self._clock()

    def read(self) -> float:
        """The current temperature in degrees Celsius, rounded to one decimal."""
        elapsed = max(0.0, self._clock() - self._started_at)
        cooled = self.start_celsius - elapsed * self.rate
        return round(max(self.target_celsius, cooled), 1)

    @property
    def is_at_temperature(self) -> bool:
        """Whether the cabinet has reached its set point."""
        return self.read() <= self.target_celsius

    def seconds_until_ready(self) -> float:
        """How long until the set point is reached, ``0.0`` if already there."""
        remaining = self.read() - self.target_celsius
        return round(max(0.0, remaining / self.rate), 1)

    def reset(self) -> None:
        """Warm the cabinet back to ``start_celsius`` and start cooling again."""
        self._started_at = self._clock()
