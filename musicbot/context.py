from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord.ext.commands.context import DeferTyping

if TYPE_CHECKING:
    from musicbot.bot import MusicBot


class BasicContext:
    def __init__(self, origin: Context | discord.Interaction):
        self.guild = origin.guild
        self.channel = origin.channel

        if isinstance(origin, discord.Interaction):
            self.interaction = origin
            self.bot = origin.client
            self.author = origin.user
        else:
            self.interaction = None
            self.bot = origin.bot
            self.author = origin.author

            self.send = origin.send
            self.typing = origin.typing

    async def send(self, *args, **kwargs):
        if self.interaction.response.is_done():
            return await self.interaction.followup.send(*args, **kwargs)
        try:
            return await self.interaction.response.send_message(
                *args, **kwargs
            )
        except discord.InteractionResponded:
            return await self.interaction.followup.send(*args, **kwargs)

    def typing(self, *, ephemeral=False) -> DeferTyping:
        return DeferTyping(self, ephemeral=ephemeral)


class SendViewMixin:
    async def send(self, *args, **kwargs):
        if hasattr(self, "message"):
            kwargs["reference"] = self.message
        audiocontroller = self.bot.audio_controllers.get(self.guild)
        if (
            audiocontroller is None
            or "view" in kwargs
            or kwargs.get("ephemeral", False)
            or (
                (channel := audiocontroller.command_channel)
                # unwrap channel from context
                and getattr(channel, "channel", channel) != self.channel
            )
        ):
            # sending ephemeral message or using different channel
            # don't bother with views
            return await super().send(*args, **kwargs)
        async with audiocontroller.message_lock:
            await audiocontroller.update_view(None)
            view = audiocontroller.make_view()
            if view:
                kwargs["view"] = view
            msg = audiocontroller.last_message = await super().send(
                *args, **kwargs
            )
        return msg


class InteractionContext(SendViewMixin, BasicContext):
    pass


class Context(SendViewMixin, commands.Context, BasicContext):
    bot: MusicBot
    guild: discord.Guild
