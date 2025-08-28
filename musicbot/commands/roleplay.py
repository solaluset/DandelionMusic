from dataclasses import dataclass

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

    @dataclass
    class CommandInfo:
        name: str
        description: str
        gif: str
        template: str
        needs_other_user: bool = True

    COMMANDS = [
        CommandInfo("hug", "Обійняти користувача", "hug", "{} обіймає {}"),
        CommandInfo("kiss", "Поцілувати користувача", "kiss", "{} цілує {}"),
        CommandInfo(
            "blush", "Зашарітися", "blush", "{} зашарівся / зашарілася", False
        ),
    ]
    COMMANDS = {info.name: info for info in COMMANDS}

    def __init__(self, bot: MusicBot):
        self.bot = bot
        bot.add_cog(self)

        for info in self.COMMANDS.values():
            args = {
                "name": info.name,
                "description": info.description,
                "integration_types": {
                    discord.IntegrationType.guild_install,
                    discord.IntegrationType.user_install,
                },
            }
            if info.needs_other_user:
                bot.slash_command(**args)(self._callback_with_user_arg)
                bot.user_command(**args)(self._callback_with_user_arg)
            else:
                bot.slash_command(**args)(self._callback_without_args)

    async def _get_gif(self, action: str) -> str:
        async with self.bot.client_session.get(ENDPOINT + action) as req:
            return (await req.json())["url"]

    async def _send_embed(self, ctx, other_user: discord.User | None):
        info = self.COMMANDS[ctx.command.name]
        format_args = [ctx.author.mention]
        if other_user:
            format_args.append(other_user.mention)
        embed = discord.Embed(
            description=info.template.format(*format_args),
            color=config.EMBED_COLOR,
        )
        embed.set_image(url=await self._get_gif(info.gif))

        await ctx.send(embed=embed)

    async def _callback_without_args(self, ctx):
        await self._send_embed(ctx, None)

    async def _callback_with_user_arg(self, ctx, user: discord.User):
        await self._send_embed(ctx, user)


def setup(bot: MusicBot):
    RolePlay(bot)
