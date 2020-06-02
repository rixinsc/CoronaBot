#!/usr/bin/env python
# -*- coding: utf-8 -*-
from discord.ext import commands
from helpers import sendError
from pathlib import Path
from classes import Bot
import os


if __name__ == "__main__":
    # change working directory to file's path
    os.chdir(Path(__file__).resolve().parent)

    bot = Bot(command_prefix=('-'), pm_help=None)

    cogs = ("corona",)

    @bot.event
    async def on_ready():
        print('Logged in as {}\n'.format(bot.user))

    @bot.event
    async def on_command_error(ctx, e):
        # Check if command has custom error handler
        if hasattr(ctx.command, 'on_error'):
            return
        cog = ctx.cog
        if cog:
            attr = '_{0.__class__.__name__}__error'.format(cog)
            if hasattr(cog, attr):
                return
        await sendError(ctx, e)

    @bot.command(hidden=True)
    @commands.is_owner()
    async def reload(ctx, *, components: str):
        """Reload a component."""
        components = (component.strip(', ') for component in components.split()
                      if component)
        for component in components:
            bot.reload_extension(component)
            await ctx.send(f'Reloaded `{component}` component.')

    @bot.command(hidden=True)
    @commands.is_owner()
    async def unload(ctx, *, components: str):
        """Unload a component."""
        components = (component.strip(', ') for component in components.split()
                      if component)
        for component in components:
            bot.unload_extension(component)
            await ctx.send(f"Unloaded `{component}` component.")

    @bot.command(hidden=True)
    @commands.is_owner()
    async def load(ctx, *, components: str):
        """Load components."""
        components = (component.strip(', ') for component in components.split()
                      if component)
        for component in components:
            bot.load_extension(component)
            await ctx.send(f'Loaded `{component}` component.')

    @reload.error
    @unload.error
    @load.error
    async def errXload(ctx, e):
        if isinstance(e, commands.CommandInvokeError):
            e = e.original

        if e is commands.errors.NotOwner:
            err = "Only owner can use this command."
        elif e is commands.errors.MissingRequiredArgument:
            err = "Please specify a component to {cmd}.".format(
                  cmd=ctx.command.name)
        elif e is commands.errors.ExtensionNotLoaded:
            err = "Can't {cmd}. Extension hasn't been loaded.".format(
                  cmd=ctx.command.name)
        elif e is commands.errors.NoEntryPointError:
            err = ("Extension doesn't have an entry point. "
                   "(Missing `setup` function)")
        elif e is commands.errors.ExtensionNotFound:
            err = "Extension not found."
        else:
            raise e

        await ctx.send(err)

    @bot.command(hidden=True)
    @commands.is_owner()
    async def shutdown(ctx):
        """Shutdown the bot."""
        await ctx.send("Shutting down...")
        print("Shutdown requested by an owner.")
        await bot.logout()

    for name in cogs:
        if name.endswith(".py"):
            name = name[:-3]
        bot.load_extension(name)

    with open('token.txt', 'r', encoding='utf8') as f:
        token = f.read().strip()

    bot.run(token)
