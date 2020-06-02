from discord.ext import commands
import traceback
import exceptions
import discord


async def sendError(ctx, err, *, log_err: bool = True) -> None:
    """
    coroutine - Send Error
    Formats error message and send it.
    """
    if isinstance(err, commands.CommandInvokeError):
        err = err.original
    standardErr = False  # is the error a valid exception?

    try:
        tberr = traceback.format_exception(type(err), err, err.__traceback__)
        tberr = ''.join(tberr)
        standardErr = True
    except AttributeError:
        tberr = err
    except Exception:
        print("An error occured while parsing a command error. "
              "The error is shown below:\n{}".format(err))
        tberr = err

    # using command improperly
    if isinstance(err, (commands.errors.MissingRequiredArgument,
                        commands.errors.BadArgument,
                        commands.errors.TooManyArguments)):
        # send help
        if ctx.invoked_subcommand:
            await ctx.send_help(str(ctx.invoked_subcommand))
        else:
            await ctx.send_help(str(ctx.command))
        return

    if isinstance(err, exceptions.BotCommandError):
        if not err.send_params[1].get("dont_log"):
            logerr = err.__cause__ if err.__cause__ is not None else err
            log(ctx, 'err', content='{}: {}'.format(
                type(logerr).__name__, logerr),
                reason='command execution error')
        if err.send_params[1].get("format"):
            await sendError(ctx, err.send_params[0], log_err=False)
        else:
            await ctx.send(err.send_params[0], **err.send_params[1])
        return

    if log_err:
        log(ctx, 'err', content=tberr)
    if standardErr:
        await ctx.send('An error occured. The exception is shown below:'
                       '\n```py\n{}: {}\n```'.format(type(err).__name__, err))
    else:
        await ctx.send('An error occured. The exception is shown below:'
                       '\n```py\n{}\n```'.format(err))


def log(ctx=None, type_: str = 'debug', **kwargs) -> None:
    """
    Log

    Usage: log(ctx, type_='debug', [content, reason])
    ·log(ctx, 'general')
    ·log(ctx, 'error', reason='reason', content='content')
    ·debug: log(content='content') (DEFAULT)
    """
    type_ = type_.lower()
    if not ctx:
        pass
    elif isinstance(ctx.channel, discord.TextChannel):
        guild_name = ctx.guild.name
        channel_name = "#" + ctx.channel.name
    elif isinstance(ctx.channel, discord.DMChannel):
        guild_name = "Personal DM"
        channel_name = ctx.channel.recipient
    elif isinstance(ctx.channel, discord.GroupChannel):
        guild_name = "Group DM"
        channel_name = str(ctx.channel)

    if type_ == "general" or type_ == "gen":
        print(f'{guild_name}({channel_name}), {ctx.author} > '
              f'{ctx.message.content}\n')
    elif type_ == 'error' or type_ == "err":
        content = str(kwargs.get('content', ''))
        print(f'{guild_name}|{channel_name}|{ctx.author}: '
              f'"{ctx.message.content}" -\n''Error has been ignored{}: \n'
              .format(' because' + ' ' if hasattr(kwargs, 'reason') else '' +
                      kwargs.get('reason', '')),
              (content if content.endswith('\n') else content + '\n')
              .replace('\n', '\n '))
    elif type_ == "debug" or type_ == "db":
        print("Debug: {}".format(kwargs.get('content', '')))
