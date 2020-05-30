class BotCommandError(Exception):
    """
    Base class of all bot's exceptions that need to be reported to user
    mostly during command execution.

    Currently supports two different error formatting styles:
    1 - send using sendError()
    Params: content: str = '', format=True, dont_log: bool = False
    2 - send using Messageable.send()
    Params: content: str = '', dont_log: bool = False, **kwargs
    """

    def __init__(self, content='', **kwargs):
        # set exception description using the most significant message
        if content:
            content = str(content)
            super().__init__(content)
        else:
            super().__init__()

        # store params to be used on Messageable.send() later in error handling
        self.send_params = (content, kwargs)


class BotValueError(BotCommandError, ValueError):
    pass


class BotRuntimeError(BotCommandError, RuntimeError):
    pass
