import sys

from discord.ext import commands

from musicbot.bot import Context, MusicBot


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


def setup(bot: MusicBot):
    bot.add_cog(Developer(bot))
