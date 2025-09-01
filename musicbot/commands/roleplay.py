from io import BytesIO
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
        CommandInfo(
            "air-kiss",
            "Надіслати повітряний поцілунок",
            "airkiss",
            "{} надсилає повітряний поцілунок {}",
        ),
        CommandInfo(
            "angry-stare",
            "Злісно дивитися",
            "angrystare",
            "{} злісно дивиться на {}",
        ),
        CommandInfo("bite", "Вкусити", "bite", "{} кусає {}"),
        CommandInfo("bleh", "Показати язик", "bleh", "{} показує язик {}"),
        CommandInfo(
            "blush", "Зашарітися", "blush", "{} зашарівся / зашарілася", False
        ),
        CommandInfo("bro-fist", "Брататися", "brofist", "{} братається з {}"),
        CommandInfo(
            "celebrate", "Святкувати", "celebrate", "{} святкує", False
        ),
        CommandInfo(
            "cheers", "Будьмо!", "cheers", "{} влаштовує гулянку", False
        ),
        CommandInfo("clap", "Аплодувати", "clap", "{} аплодує", False),
        CommandInfo(
            "confused",
            "Розгубитися",
            "confused",
            "{} почувається розгублено",
            False,
        ),
        CommandInfo(
            "cool", "Почуватися круто", "cool", "{} почувається круто", False
        ),
        CommandInfo("cry", "Плакати", "cry", "{} плаче", False),
        CommandInfo(
            "cuddle", "Міцно обійняти", "cuddle", "{} міцно обіймає {}"
        ),
        CommandInfo("dance", "Танцювати", "dance", "{} танцює", False),
        CommandInfo(
            "drool", "Пускати слину", "drool", "{} пускає слину", False
        ),
        CommandInfo(
            "evil-laugh",
            "Зловісно сміятися",
            "evillaugh",
            "{} зловісно сміється",
            False,
        ),
        CommandInfo(
            "facepalm", "Фейспалм", "facepalm", "{} робить фейспалм", False
        ),
        CommandInfo(
            "handhold", "Триматися за руки", "handhold", "{} тримає {} за руку"
        ),
        CommandInfo(
            "happy",
            "Почуватися щасливо",
            "happy",
            "{} почувається щасливо",
            False,
        ),
        CommandInfo(
            "headbang",
            "Битися головою об стіну",
            "headbang",
            "{} б'ється головою об стіну",
            False,
        ),
        CommandInfo("hug", "Обійняти користувача", "hug", "{} обіймає {}"),
        CommandInfo("huh", "Га?", "huh", "{} розгублено дивиться", False),
        CommandInfo("kiss", "Поцілувати користувача", "kiss", "{} цілує {}"),
        CommandInfo("laugh", "Сміятися", "laugh", "{} сміється", False),
        CommandInfo("lick", "Лизати користувача", "lick", "{} лиже {}"),
        CommandInfo(
            "love", "Відчувати любов", "love", "{} випромінює любов", False
        ),
        CommandInfo("mad", "Злитися", "mad", "{} злиться", False),
        CommandInfo("nervous", "Нервувати", "nervous", "{} нервує", False),
        CommandInfo("no", "Заперечувати", "no", "{} заперечує", False),
        CommandInfo("nom", "Їсти", "nom", "{} їсть", False),
        CommandInfo(
            "nosebleed",
            "Кров з носа",
            "nosebleed",
            "У {} йде кров з носа",
            False,
        ),
        CommandInfo("nuzzle", "Тертися", "nuzzle", "{} треться об {}"),
        CommandInfo(
            "nyah",
            "Робити милий вигляд",
            "nyah",
            "{} має милий вигляд",
            False,
        ),
        CommandInfo("pat", "Гладити", "pat", "{} гладить {}"),
        CommandInfo("peek", "Підглядати", "peek", "{} підглядає за {}"),
        CommandInfo("pinch", "Ущипнути", "pinch", "{} щипає {}"),
        CommandInfo("poke", "Тицьнути", "poke", "{} тицяє {}"),
        CommandInfo("pout", "Дутися", "pout", "{} дується", False),
        CommandInfo("punch", "Вдарити", "punch", "{} б'є {}"),
        CommandInfo("roll", "Крутитися", "roll", "{} крутиться", False),
        CommandInfo("run", "Бігти", "run", "{} біжить", False),
        CommandInfo("sad", "Сумувати", "sad", "{} сумує", False),
        CommandInfo("scared", "Злякатися", "scared", "{} боїться", False),
        CommandInfo("shout", "Кричати на когось", "shout", "{} кричить на {}"),
        CommandInfo(
            "shrug", "Знизати плечима", "shrug", "{} знизує плечима", False
        ),
        CommandInfo("shy", "Соромитися", "shy", "{} соромиться", False),
        CommandInfo("sigh", "Зітхати", "sigh", "{} зітхає", False),
        CommandInfo("sip", "Зробити ковток", "sip", "{} п'є", False),
        CommandInfo("slap", "Дати ляпаса", "slap", "{} дає ляпаса {}"),
        CommandInfo("sleep", "Спати", "sleep", "{} спить", False),
        CommandInfo(
            "slow-clap",
            "Повільно аплодувати",
            "slowclap",
            "{} повільно аплодує",
            False,
        ),
        CommandInfo(
            "smack", "Вдарити по голові", "smack", "{} б'є {} по голові"
        ),
        CommandInfo("smile", "Посміхатися", "smile", "{} посміхається", False),
        CommandInfo(
            "smug",
            "Почуватися самовдоволено",
            "smug",
            "{} почувається самовдоволено",
            False,
        ),
        CommandInfo("sneeze", "Чхнути", "sneeze", "{} чхає", False),
        CommandInfo(
            "sorry", "Просити вибачення", "sorry", "{} просить вибачення у {}"
        ),
        CommandInfo("stare", "Дивитися", "stare", "{} дивиться на {}"),
        CommandInfo("rp-stop", "Зупиняти когось", "stop", "{} зупиняє {}"),
        CommandInfo(
            "surprised", "Дивуватися", "surprised", "{} дивується", False
        ),
        CommandInfo("sweat", "Пітніти", "sweat", "{} пітніє", False),
        CommandInfo(
            "thumbsup",
            "Палець вгору",
            "thumbsup",
            "{} підіймає великий палець вгору",
            False,
        ),
        CommandInfo("tickle", "Лоскотати", "tickle", "{} лоскоче {}"),
        CommandInfo(
            "tired",
            "Почуватися втомлено",
            "tired",
            "{} почувається втомлено",
            False,
        ),
        CommandInfo("wave", "Махати руками", "wave", "{} махає руками до {}"),
        CommandInfo("wink", "Підморгувати", "wink", "{} підморгує {}"),
        CommandInfo("woah", "Захоплюватися", "woah", "{} захоплюється", False),
        CommandInfo("yawn", "Позіхати", "yawn", "{} позіхає", False),
        CommandInfo("yay", "Радіти", "yay", "{} радіє", False),
        CommandInfo("yes", "Погоджуватися", "yes", "{} погоджується", False),
    ]
    COMMANDS = {info.name: info for info in COMMANDS}
    # a stupid discord limit - no more than 5 user commands
    USER_COMMANDS = {"hug", "kiss", "bite", "handhold", "pat"}

    def __init__(self, bot: MusicBot):
        self.bot = bot
        self.gif_cache = {}
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
                if info.name in self.USER_COMMANDS:
                    bot.user_command(**args)(self._callback_with_user_arg)
            else:
                bot.slash_command(**args)(self._callback_without_args)

    async def _get_gif(self, action: str) -> bytes:
        async with self.bot.client_session.get(ENDPOINT + action) as req:
            url = (await req.json())["url"]

        if url not in self.gif_cache:
            async with self.bot.client_session.get(url) as req:
                self.gif_cache[url] = await req.read()
        return self.gif_cache[url]

    async def _send_embed(self, ctx, other_user: discord.User | None):
        await ctx.defer()

        info = self.COMMANDS[ctx.command.name]
        format_args = [ctx.author.mention]
        if other_user:
            format_args.append(other_user.mention)
        embed = discord.Embed(
            description=info.template.format(*format_args),
            color=config.EMBED_COLOR,
        )
        embed.set_image(url="attachment://action.gif")

        await ctx.send(
            embed=embed,
            file=discord.File(
                BytesIO(await self._get_gif(info.gif)), "action.gif"
            ),
        )

    async def _callback_without_args(self, ctx):
        await self._send_embed(ctx, None)

    async def _callback_with_user_arg(self, ctx, user: discord.User):
        await self._send_embed(ctx, user)


def setup(bot: MusicBot):
    RolePlay(bot)
