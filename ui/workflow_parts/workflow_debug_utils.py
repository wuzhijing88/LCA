import logging


DEBUG_ENABLED = False


def debug_print(*args, **kwargs):
    if not DEBUG_ENABLED:
        return

    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "")
    message = sep.join(str(arg) for arg in args)
    if end:
        message = f"{message}{end}"
    logging.getLogger(__name__).debug(message)
