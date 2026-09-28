from discord import Interaction, Message
from discord.ext import commands
from discord.app_commands import context_menu, guild_only

from musicbot import linkutils, utils
from musicbot.bot import MusicBot
from musicbot.context import InteractionContext


class Button(commands.Cog):
    def __init__(self, bot: MusicBot):
        self.bot = bot
        bot.tree.add_command(self.build_context_menu())

    @staticmethod
    def _get_links(msg: Message):
        links = linkutils.get_urls(msg.content)
        links.extend(a.url for a in msg.attachments)
        return [
            link
            for link in links
            if linkutils.identify_url(link) != linkutils.SiteTypes.UNKNOWN
        ]

    def build_context_menu(self):
        @context_menu(name="play")
        @guild_only()
        async def _play(inter: Interaction, message: Message):
            ctx = InteractionContext(inter)

            links = self._get_links(message)
            if not links:
                return await ctx.send(
                    "No supported links found.", ephemeral=True
                )

            async with ctx.typing():
                await utils.play_check(ctx)

                audiocontroller = ctx.bot.audio_controllers[ctx.guild]
                audiocontroller.command_channel = ctx
                for url in links:
                    await audiocontroller.play(ctx, url)

        return _play


async def setup(bot: MusicBot):
    await bot.add_cog(Button(bot))
