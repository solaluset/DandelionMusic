from discord import Interaction, Message
from discord.ext import commands
from discord.app_commands import context_menu, guild_only

from musicbot import utils
from musicbot.bot import MusicBot
from musicbot.context import InteractionContext


class Button(commands.Cog):
    def __init__(self, bot: MusicBot):
        self.bot = bot
        bot.tree.add_command(self.build_context_menu())

    def build_context_menu(self):
        @context_menu(name="play")
        @guild_only()
        async def _play(inter: Interaction, message: Message):
            ctx = InteractionContext(inter)

            async with ctx.typing():
                await utils.play_check(ctx)

                audiocontroller = ctx.bot.audio_controllers[ctx.guild]
                audiocontroller.command_channel = ctx
                await audiocontroller.play(ctx, message.jump_url)

        return _play


async def setup(bot: MusicBot):
    await bot.add_cog(Button(bot))
