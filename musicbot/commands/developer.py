import sys
import asyncio
from io import StringIO
from typing import List
from textwrap import TextWrapper
from traceback import print_exc
from contextlib import redirect_stdout

import discord
from discord.ext import commands
from discord.ext.pages import Paginator
from aioconsole import aexec

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


def setup(bot: MusicBot):
    bot.add_cog(Developer(bot))
