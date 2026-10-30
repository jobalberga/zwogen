"""Isolated, bounded vehicle operation; invoked only by the private worker."""
import logging
import signal
import sys

from .cloud_runtime import job

def main(task_id, handler=job, timeout=190):
    def expired(signum, frame):
        raise TimeoutError("Vehicle operation deadline")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        handler(task_id)
    except Exception as error:
        logging.error("Vehicle task incomplete (%s)", type(error).__name__)
        raise SystemExit(1) from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    main(sys.argv[1])
