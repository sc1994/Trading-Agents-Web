"""Credential redaction covering all Python loggers during a serialized run."""

import logging
from contextlib import contextmanager


@contextmanager
def redact_logs(redact):
    """Sanitize records before handlers, including graph worker threads.

    A root logger filter misses propagated child records and private handlers.
    The record factory reaches both, including handlers created during the run.
    Freeze exception text now so formatters cannot later reveal raw exceptions.
    The caller holds the process-wide run lock until the overlay is restored.
    """
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact(formatter.formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return record

    logging.setLogRecordFactory(factory)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)
