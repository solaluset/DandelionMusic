import sys
import asyncio
from io import StringIO
from typing import List
from textwrap import TextWrapper
from traceback import print_exc
from contextlib import redirect_stdout

import discord
from discord.ext import commands, bridge
from discord.ext.pages import Paginator
from discord.ext.bridge import BridgeOption
from aioconsole import aexec

from config import config
from musicbot.bot import Context, MusicBot


class Splitter(TextWrapper):
    def __init__(self, width: int):
        super().__init__(
            width, replace_whitespace=False, drop_whitespace=False, tabsize=4
        )

    def _split(self, text: str) -> List[str]:
        return text.splitlines(True)

    def _handle_long_word(
        self,
        reversed_chunks: List[str],
        cur_line: List[str],
        cur_len: int,
        width: int,
    ) -> None:
        # split by words if possible
        split_chunk = super()._split(reversed_chunks.pop())
        split_chunk.reverse()
        reversed_chunks.extend(split_chunk)
        super()._handle_long_word(reversed_chunks, cur_line, cur_len, width)


OUTPUT_FORMAT = "```\n\u200b{}\n```"
_paginate = Splitter(2002 - len(OUTPUT_FORMAT)).wrap


class Developer(commands.Cog):
    def __init__(self, bot: MusicBot):
        self.bot = bot

    @commands.command(
        name="shutdown",
        hidden=True,
    )
    @commands.is_owner()
    async def _shutdown(self, ctx: Context):
        await ctx.send("Shutting down...")
        # hide SystemExit error message
        sys.excepthook = lambda *_: None
        sys.exit()

    @commands.command(
        name="execute",
        hidden=True,
        aliases=("exec",),
    )
    @commands.is_owner()
    async def _execute(self, ctx: Context, *, code: str):
        if code.startswith("```"):
            code = code.partition("\n")[2].rstrip("`")
        else:
            code = code.strip("`")

        namespace = {
            "ctx": ctx,
            "bot": ctx.bot,
            "discord": discord,
            "asyncio": asyncio,
        }

        output = StringIO()
        with redirect_stdout(output):
            try:
                await aexec(code, namespace)
            except Exception:
                print_exc(file=output)
        output = output.getvalue()

        if output and not output.isspace():
            pages = (page.rstrip() for page in _paginate(output))
            pages = [OUTPUT_FORMAT.format(page) for page in pages if page]
            if len(pages) == 1:
                await ctx.send(pages[0])
            else:
                await Paginator(pages).send(ctx)
        else:
            try:
                suppress = ctx.channel.last_message.author == ctx.me
            except AttributeError:
                suppress = False
            if not suppress:
                await ctx.send("No output.")

    @bridge.bridge_group(
        name="guild_whitelist",
        aliases=("gw",),
        usage="[action [guild id]]",
        invoke_without_command=True,
    )
    @commands.is_owner()
    async def _guild_whitelist(
        self, ctx: Context, *, inexistent_subcommand=None
    ):
        if inexistent_subcommand is not None:
            await ctx.send("`Error: Unknown subcommand`")
        else:
            await self._show_guild_whitelist_callback(ctx)

    async def _show_guild_whitelist_callback(self, ctx: Context):
        if not config.GUILD_WHITELIST:
            await ctx.send("Whitelist is disabled.")
            return
        lines = []
        for id_ in config.GUILD_WHITELIST:
            guild = ctx.bot.get_guild(id_)
            if guild:
                lines.append(f"{id_} {guild.name}")
            else:
                lines.append(str(id_))
        await ctx.send("```\n" + "\n".join(lines) + "```")

    _show_guild_whitelist = _guild_whitelist.command(name="show")(
        commands.is_owner()(_show_guild_whitelist_callback)
    )

    @_guild_whitelist.command(name="add")
    @commands.is_owner()
    async def _guild_whitelist_add(self, ctx: Context, *, id: str):
        config.GUILD_WHITELIST.append(int(id))
        config.save()
        await ctx.send("Whitelist updated.")

    @staticmethod
    def _guild_whitelist_remove_autocomplete(
        ctx: discord.AutocompleteContext,
    ) -> List[str]:
        value = ctx.value.lower()
        lines = []
        for id_ in config.GUILD_WHITELIST:
            guild = ctx.bot.get_guild(id_)
            if guild:
                lines.append(f"{id_} {guild.name}")
            else:
                lines.append(str(id_))
        return [s for s in lines if value in s.lower()]

    @_guild_whitelist.command(name="remove")
    @commands.is_owner()
    async def _guild_whitelist_remove(
        self,
        ctx: Context,
        *,
        id: BridgeOption(
            str, autocomplete=_guild_whitelist_remove_autocomplete
        ),
    ):
        id = int(id.split()[0])
        config.GUILD_WHITELIST.remove(id)
        config.save()

        guild = ctx.bot.get_guild(id)
        if guild is not None:
            message = "Whitelist updated, leaving the guild."
        else:
            message = "Whitelist updated."
        await ctx.send(message)
        if guild is not None:
            await guild.leave()


def setup(bot: MusicBot):
    bot.add_cog(Developer(bot))
