import logging
from io import StringIO

from uvicorn.logging import AccessFormatter

from web.logging import redact_logs


def test_access_formatter_keeps_status_and_redacts_structured_credentials():
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(AccessFormatter(
        '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        use_colors=False,
    ))
    logger = logging.getLogger("uvicorn.access")
    prior_level, prior_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        with redact_logs(lambda text: text.replace("key%2Bphrase", "[REDACTED]").replace(
            "key+phrase", "[REDACTED]"
        )):
            logger.info(
                '%s - "%s %s HTTP/%s" %d',
                "client-key+phrase", "GET", "/?token=key%2Bphrase&raw=key+phrase", "1.1", 200,
            )
        log = output.getvalue()
        assert 'client-[REDACTED] - "GET /?token=[REDACTED]&raw=[REDACTED] HTTP/1.1" 200 OK' in log
        assert "key+phrase" not in log
        assert "key%2Bphrase" not in log
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prior_level)
        logger.propagate = prior_propagate
