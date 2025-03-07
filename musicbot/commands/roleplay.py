import discord
from discord.ext import commands

from config import config
from musicbot.bot import MusicBot


ENDPOINT = "https://api.otakugifs.xyz/gif?reaction="


class RolePlay(commands.Cog):
    """Role play related commands

    Attributes:
        bot: The instance of the bot that is executing the commands.
    """

    def __init__(self, bot: MusicBot):
        self.bot = bot

    @discord.commands.user_command(
        name="hug",
        description="Обійняти користувача",
        integration_types={
            discord.IntegrationType.guild_install,
            discord.IntegrationType.user_install,
        },
    )
    async def _hug(self, ctx, user: discord.User):
        embed = discord.Embed(
            description=f"{ctx.author.mention} обіймає {user.mention}",
            color=config.EMBED_COLOR,
        )
        embed.set_image(url=await self.get_gif("hug"))

        await ctx.send(embed=embed)

    @discord.commands.user_command(
        name="kiss",
        description="Поцілувати користувача",
        integration_types={
            discord.IntegrationType.guild_install,
            discord.IntegrationType.user_install,
        },
    )
    async def _kiss(self, ctx, user: discord.User):
        embed = discord.Embed(
            description=f"{ctx.author.mention} цілує {user.mention}",
            color=config.EMBED_COLOR,
        )
        embed.set_image(url=await self.get_gif("kiss"))

        await ctx.send(embed=embed)

    async def get_gif(self, action: str) -> str:
        async with self.bot.client_session.get(ENDPOINT + action) as req:
            return (await req.json())["url"]


def setup(bot: MusicBot):
    bot.add_cog(RolePlay(bot))
