import discord
from discord.ext import commands
from discord.ext.commands import Context
from discord import Option, SlashCommandOptionType as OptionType
import logging
from datetime import datetime, timezone
from main import parse_duration, format_duration
import config
import asyncio
import json
from pathlib import Path
import os
from typing import Optional

# Import language manager
import sys
sys.path.append(str(Path(__file__).parent.parent))
from utils.language_manager import get_text, language_manager
from utils.config_manager import config_manager

logger = logging.getLogger(__name__)

BOT_ACTIONS_LOG = Path('bot_actions.log')
MUTED_USERS_FILE = Path('muted_users.json')

def log_action_to_file(action: str):
    with BOT_ACTIONS_LOG.open('a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {action}\n")

def add_mute_to_file(user_id, username, until, reason, guild_id=None):
    mutes = []
    if MUTED_USERS_FILE.exists():
        with MUTED_USERS_FILE.open(encoding='utf-8') as f:
            try:
                mutes = json.load(f)
            except json.JSONDecodeError:
                mutes = []
    
    mutes = [m for m in mutes if not (
        m.get('user_id') == str(user_id) and 
        (guild_id is None or str(m.get('guild_id')) == str(guild_id))
    )]
    
    mutes.append({
        'user_id': str(user_id),
        'username': username,
        'until': until,
        'reason': reason,
        'guild_id': str(guild_id) if guild_id is not None else None
    })
    
    with MUTED_USERS_FILE.open('w', encoding='utf-8') as f:
        json.dump(mutes, f, ensure_ascii=False, indent=2)

def remove_mute_from_file(user_id, guild_id=None):
    mutes = []
    if MUTED_USERS_FILE.exists():
        with MUTED_USERS_FILE.open(encoding='utf-8') as f:
            try:
                mutes = json.load(f)
            except json.JSONDecodeError:
                mutes = []
    
    user_id = str(user_id)
    guild_id = str(guild_id) if guild_id is not None else None
    
    mutes = [
        m for m in mutes 
        if not (m.get('user_id') == user_id and 
               (guild_id is None or str(m.get('guild_id')) == guild_id))
    ]
    
    with MUTED_USERS_FILE.open('w', encoding='utf-8') as f:
        json.dump(mutes, f, ensure_ascii=False, indent=2)

def has_any_role(member, role_ids):
    return any(role.id in role_ids for role in member.roles)

def get_log_channel(guild: discord.Guild):
    channel = None
    
    try:
        log_channel_id = getattr(config, 'LOG_CHANNEL_ID', None)
        if log_channel_id:
            ch = guild.get_channel(int(log_channel_id))
            if isinstance(ch, discord.TextChannel):
                return ch
    except (ValueError, AttributeError):
        pass
    
    common_names = ['mod-logs', 'moderation-logs', 'logs', 'modlogs', 'audit-logs']
    for ch in guild.text_channels:
        if ch.name.lower() in common_names and ch.permissions_for(guild.me).send_messages:
            return ch
    
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
        
    return None

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_mutes_task = self.bot.loop.create_task(self.check_mutes_loop())
        
    def get_guild_language(self, guild_id: int) -> str:
        return config_manager.get_guild_language(guild_id)
        
    @commands.slash_command(
        name="setup",
        description="⚙️ Настроить бота / Configure bot"
    )
    @commands.has_permissions(administrator=True)
    async def setup_bot(
        self,
        ctx: discord.ApplicationContext,
        language: discord.Option(
            str,
            description="🌐 Выберите язык бота / Select bot language",
            choices=["Русский", "English"],
            required=True,
            name="язык",
            name_localizations={"en-US": "language"}
        ),
    ):
        """
        Настройка языка бота для этого сервера.
        Настройки сохраняются и применяются ко всем командам.
        
        Configure bot language for this server.
        Settings are saved and applied to all commands.
        """
        lang_code = 'ru' if language == "Русский" else 'en'
        config_manager.set_guild_language(ctx.guild.id, lang_code)
        
        # Create embed with setup results
        embed = discord.Embed(
            color=discord.Color.green(),
            title="✅ " + ("Настройки сохранены" if lang_code == 'ru' else "Settings saved"),
            description=(
                "Теперь бот будет использовать **Русский** язык на этом сервере.\n"
                "Вы можете изменить язык в любое время снова используя `/setup`."
                if lang_code == 'ru' else
                "The bot will now use **English** on this server.\n"
                "You can change the language anytime using `/setup` again."
            )
        )
        
        # Add helpful tips based on language
        if lang_code == 'ru':
            embed.add_field(
                name="ℹ️ Доступные команды",
                value="""- `/мут @пользователь` - Задать мут
- `/размут @пользователь` - Снять мут
- `/бан @пользователь` - Забанить пользователя
- `/кик @пользователь` - Кикнуть пользователя
- `/настройки` - Показать текущие настройки

💡 Подсказка: Наведите курсор на параметры команд, чтобы увидеть подсказки!""",
                inline=False
            )
        else:
            embed.add_field(
                name="ℹ️ Available Commands",
                value="""- `/mute @user` - Mute a user
- `/unmute @user` - Unmute a user
- `/ban @user` - Ban a user
- `/kick @user` - Kick a user
- `/settings` - Show current settings

💡 Tip: Hover over command parameters to see tooltips!""",
                inline=False
            )
            
        embed.set_footer(
            text=("🔧 Напишите /help для справки" if lang_code == 'ru' 
                 else "🔧 Type /help for help")
        )
        
        await ctx.respond(embed=embed, ephemeral=True)
        
        # Log the language change
        self.log_action("language_change", str(ctx.author), f"Set language to {language}", "", lang_code)
    async def check_mutes_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await self.check_expired_mutes()
            await asyncio.sleep(60)  # Проверять раз в минуту
    async def check_expired_mutes(self):
        if not MUTED_USERS_FILE.exists():
            return
            
        lang = self.get_guild_language(ctx.guild.id) if hasattr(ctx, 'guild') else 'ru'
            
        with MUTED_USERS_FILE.open(encoding='utf-8') as f:
            try:
                mutes = json.load(f)
            except json.JSONDecodeError:
                mutes = []
                
        now = datetime.now(timezone.utc)
        updated_mutes = []
        
        for mute in mutes:
            try:
                until = datetime.strptime(mute['until'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            except (ValueError, KeyError):
                updated_mutes.append(mute)
                continue
                
            if until > now:
                updated_mutes.append(mute)
                continue
                
            target_member = None
            guild_id = mute.get('guild_id')
            
            if guild_id:
                guild = self.bot.get_guild(int(guild_id))
                if guild:
                    target_member = guild.get_member(int(mute['user_id']))
            else:
                for g in self.bot.guilds:
                    m = g.get_member(int(mute['user_id']))
                    if m:
                        target_member = m
                        break
                        
            if target_member:
                try:
                    await target_member.timeout(None, reason='Автоматическое снятие мута (время истекло)')
                except discord.HTTPException:
                    pass
                    
            log_action_to_file(
                get_text('auto_actions.unmute', lang).format(
                    mute['username'], 
                    mute['user_id']
                )
            )
        with MUTED_USERS_FILE.open('w', encoding='utf-8') as f:
            json.dump(updated_mutes, f, ensure_ascii=False, indent=2)

    def log_action(self, action: str, moderator: str, target: str, reason: str, duration: str = None, lang: str = None):
        if lang is None:
            lang = 'ru'  # Default to Russian if no language context
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration_str = f" {get_text('moderation.mute.duration', lang).lower()} {duration}" if duration else ""
        log_message = f"[{timestamp}] {action.upper()}: {moderator} -> {target}{duration_str} | {get_text('moderation.mute.reason', lang)}: {reason}"
        logger.info(log_message)
        if not getattr(config, 'SUPPRESS_LOGS', False):
            print(log_message)

    async def send_moderation_embed(self, ctx, action: str, target: discord.Member, reason: str, duration: str = None, dm: bool = False, lang: str = None):
        if lang is None:
            lang = self.get_guild_language(ctx.guild.id) if hasattr(ctx, 'guild') else 'ru'
        titles = {
            "mute": get_text('moderation.mute.title', lang),
            "timeout": get_text('moderation.timeout.title', lang),
            "ban": get_text('moderation.ban.title', lang),
            "kick": get_text('moderation.kick.title', lang),
            "unmute": get_text('moderation.unmute.title', lang),
            "unban": get_text('moderation.unban.title', lang),
            "voicemute": get_text('moderation.voicemute.title', lang),
            "unvoicemute": get_text('moderation.unvoicemute.title', lang)
        }
        embed = discord.Embed(
            title=titles.get(action, action.title()),
            description=f"**Пользователь:** {target.mention}\n**Причина:** {reason}",
            color=discord.Color.red() if action in ["mute", "timeout", "ban", "kick", "voicemute"] else discord.Color.green(),
            timestamp=datetime.now()
        )
        if duration:
            embed.add_field(name="Длительность", value=duration, inline=True)
        if hasattr(ctx, 'author'):
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
        elif hasattr(ctx, 'user'):
            embed.add_field(name="Модератор", value=ctx.user.mention, inline=True)
        embed.set_footer(text=f"ID: {target.id}")
        if dm:
            try:
                await target.send(embed=embed)
            except Exception:
                pass
        else:
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()

    async def send_log_to_channel(self, guild, embed):
        log_channel = get_log_channel(guild)
        if log_channel:
            await log_channel.send(embed=embed)

    # --- МУТ (timeout) ---
    async def _mute_user(self, ctx, member: discord.Member, duration: str, reason: str, lang: str = None) -> bool:
        if lang is None:
            lang = self.get_guild_language(ctx.guild.id)
        if member.guild_permissions.administrator:
            await ctx.send(get_text('errors.admin_protected', lang))
            return False
            
        try:
            duration_delta = parse_duration(duration)
            duration_str = format_duration(duration_delta)
            until = datetime.now(timezone.utc) + duration_delta
            await member.timeout(until, reason=reason)
            
            self.log_action("mute", str(ctx.author), str(member), reason, duration_str, lang)
            log_action_to_file(
                f"[MUTE] {member} ({member.id}) {get_text('moderation.until', lang, lang=lang)} "
                f"{until.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"{get_text('moderation.reason', lang, lang=lang)}: {reason}"
            )
            
            add_mute_to_file(
                member.id, 
                str(member), 
                until.strftime('%Y-%m-%d %H:%M:%S'), 
                reason, 
                guild_id=ctx.guild.id
            )
            
            embed = discord.Embed(
                title=get_text(f'moderation.mute.title', lang),
                description=get_text('moderation.mute.description', lang).format(
                    member.mention, reason
                ),
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name=get_text('moderation.mute.duration', lang), 
                value=duration_str, 
                inline=True
            )
            
            moderator = ctx.author.mention if hasattr(ctx, 'author') else ctx.user.mention
            embed.add_field(
                name=get_text('moderation.mute.moderator', lang), 
                value=moderator, 
                inline=True
            )
            
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(
                name='',
                value=get_text('moderation.mute.appeal', lang),
                inline=False
            )
            
            if isinstance(ctx, commands.Context):
                msg = await ctx.send(embed=embed)
                await asyncio.sleep(5)
                await msg.delete()
            else:
                await ctx.respond(embed=embed, ephemeral=True)
                
            await self.send_moderation_embed(ctx, "mute", member, reason, duration_str, dm=True, lang=lang)
            await self.send_log_to_channel(ctx.guild, embed)
            return True
            
        except ValueError as e:
            error_msg = get_text('errors.invalid_duration', lang).format(str(e))
            if isinstance(ctx, commands.Context):
                await ctx.send(error_msg)
            else:
                await ctx.respond(error_msg, ephemeral=True)
            return False
        except Exception as e:
            logger.error(f"Error in mute command: {e}")
            error_msg = get_text('errors.unknown', lang)
            if isinstance(ctx, commands.Context):
                await ctx.send(error_msg)
            else:
                await ctx.respond(error_msg, ephemeral=True)
            return False

    @commands.command(name="mute", aliases=["мьют"], help="Замутить пользователя")
    @commands.has_permissions(administrator=True)
    async def prefix_mute(self, ctx: Context, member: discord.Member, duration: str = "5m", *, reason: str = None):
        reason = reason or get_text('moderation.no_reason', 'ru')
        await self._mute_user(ctx, member, duration, reason, 'ru')
        try:
            duration_delta = parse_duration(duration)
            duration_str = format_duration(duration_delta)
            until = datetime.now(timezone.utc) + duration_delta
            await member.timeout(until, reason=reason)
            self.log_action("mute", str(ctx.author), str(member), reason, duration_str)
            # --- LOG TO FILE ---
            log_action_to_file(f"[MUTE] {member} ({member.id}) до {until.strftime('%Y-%m-%d %H:%M:%S')} | Причина: {reason}")
            add_mute_to_file(member.id, str(member), until.strftime('%Y-%m-%d %H:%M:%S'), reason, guild_id=ctx.guild.id)
            embed = discord.Embed(
                title="🔇 Мут",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Длительность", value=duration_str, inline=True)
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "mute", member, reason, duration_str, dm=True)
            await self.send_log_to_channel(ctx.guild, embed)
        except ValueError as e:
            await ctx.send(f"❌ Неверный формат длительности: {e}")
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для мута этого пользователя!")
        except Exception as e:
            logger.error(f"Ошибка в команде mute: {e}")
            await ctx.send("❌ Произошла ошибка при муте пользователя.")

    @commands.slash_command(name="mute", description="Замутить пользователя на время")
    @commands.has_permissions(administrator=True)
    async def mute_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        duration: Option(str, "Время действия (10мин, 15ч и т.д. Бессрочно если не указано)", default="5m"),
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        if user.guild_permissions.administrator:
            await ctx.respond("❌ Нельзя замутить администратора!", ephemeral=True)
            return
        try:
            duration_delta = parse_duration(duration)
            duration_str = format_duration(duration_delta)
            until = datetime.now(timezone.utc) + duration_delta
            await user.timeout(until, reason=reason)
            self.log_action("mute", str(ctx.author), str(user), reason, duration_str)
            # --- LOG TO FILE ---
            log_action_to_file(f"[MUTE] {user} ({user.id}) до {until.strftime('%Y-%m-%d %H:%M:%S')} | Причина: {reason}")
            add_mute_to_file(user.id, str(user), until.strftime('%Y-%m-%d %H:%M:%S'), reason, guild_id=ctx.guild.id)
            embed = discord.Embed(
                title="🔇 Мут",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Длительность", value=duration_str, inline=True)
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_moderation_embed(ctx, "mute", user, reason, duration_str, dm=True)
            await self.send_log_to_channel(ctx.guild, embed)
        except ValueError as e:
            await ctx.respond(f"❌ Неверный формат длительности: {e}", ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("❌ У меня нет прав для мута этого пользователя!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка в команде mute: {e}")
            await ctx.respond("❌ Произошла ошибка при муте пользователя.", ephemeral=True)

    # --- БАН ---
    @commands.command(name="ban", aliases=["бан"], help="Забанить пользователя")
    @commands.has_permissions(administrator=True)
    async def prefix_ban(self, ctx: Context, member: discord.Member, *, reason: str = "Без причины"):
        try:
            await member.ban(reason=reason)
            self.log_action("ban", str(ctx.author), str(member), reason)
            embed = discord.Embed(
                title="⛔ Бан",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "ban", member, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для бана этого пользователя!")
        except Exception as e:
            logger.error(f"Ошибка в команде ban: {e}")
            await ctx.send("❌ Произошла ошибка при бане пользователя.")

    @commands.slash_command(name="ban", description="Забанить пользователя на сервере")
    @commands.slash_command(name="бан", description="Забанить пользователя на сервере")
    @commands.has_permissions(administrator=True)
    async def ban_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default=None),
                        language: Option(str, "Язык", choices=["English", "Русский"], default="Русский")):
        lang = 'en' if language == "English" else 'ru'
        reason = reason or get_text('moderation.no_reason', lang)
        try:
            await user.ban(reason=reason)
            self.log_action("ban", str(ctx.author), str(user), reason, lang=lang)
            embed = discord.Embed(
                title="⛔ Бан",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.respond("❌ У меня нет прав для бана этого пользователя!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка в команде ban: {e}")
            await ctx.respond("❌ Произошла ошибка при бане пользователя.", ephemeral=True)

    # --- КИК ---
    @commands.command(name="kick", help="Кикнуть пользователя")
    @commands.has_permissions(administrator=True)
    async def prefix_kick(self, ctx: Context, member: discord.Member, *, reason: str = "Без причины"):
        try:
            await member.kick(reason=reason)
            self.log_action("kick", str(ctx.author), str(member), reason)
            embed = discord.Embed(
                title="👢 Кик",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "kick", member, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для кика этого пользователя!")
        except Exception as e:
            logger.error(f"Ошибка в команде kick: {e}")
            await ctx.send("❌ Произошла ошибка при кике пользователя.")

    @commands.slash_command(name="kick", description="Кикнуть пользователя с сервера")
    @commands.slash_command(name="кик", description="Кикнуть пользователя с сервера")
    @commands.has_permissions(administrator=True)
    async def kick_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default=None),
                        language: Option(str, "Язык", choices=["English", "Русский"], default="Русский")):
        lang = 'en' if language == "English" else 'ru'
        reason = reason or get_text('moderation.no_reason', lang)
        try:
            await user.kick(reason=reason)
            self.log_action("kick", str(ctx.author), str(user), reason, lang=lang)
            embed = discord.Embed(
                title="👢 Кик",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_moderation_embed(ctx, "kick", user, reason, lang=lang)
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.respond("❌ У меня нет прав для кика этого пользователя!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка в команде kick: {e}")
            await ctx.respond("❌ Произошла ошибка при кике пользователя.", ephemeral=True)

    # --- СНЯТИЕ МУТА ---
    @commands.command(name="unmute", help="Снять мут с пользователя")
    @commands.has_permissions(administrator=True)
    async def prefix_unmute(self, ctx: Context, member: discord.Member, *, reason: str = "Без причины"):
        try:
            await member.timeout(None, reason=reason)
            self.log_action("unmute", str(ctx.author), str(member), reason)
            # --- LOG TO FILE ---
            log_action_to_file(f"[UNMUTE] {member} ({member.id}) | Причина: {reason}")
            remove_mute_from_file(member.id, guild_id=ctx.guild.id)
            embed = discord.Embed(
                title="🔊 Снятие мута",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "unmute", member, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для снятия мута с этого пользователя!")
        except Exception as e:
            logger.error(f"Ошибка в команде unmute: {e}")
            await ctx.send("❌ Произошла ошибка при снятии мута.")

    @commands.slash_command(name="unmute", description="Снять мут с пользователя")
    @commands.slash_command(name="размут", description="Снять мут с пользователя")
    @commands.has_permissions(administrator=True)
    async def unmute_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default=None),
                        language: Option(str, "Язык", choices=["English", "Русский"], default="Русский")):
        lang = 'en' if language == "English" else 'ru'
        reason = reason or get_text('moderation.no_reason', lang)
        try:
            await user.timeout(None, reason=reason)
            self.log_action("unmute", str(ctx.author), str(user), reason, lang=lang)
            # --- LOG TO FILE ---
            log_action_to_file(f"[UNMUTE] {user} ({user.id}) | Причина: {reason}")
            remove_mute_from_file(user.id, guild_id=ctx.guild.id)
            embed = discord.Embed(
                title="🔊 Снятие мута",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_moderation_embed(ctx, "unmute", user, reason, lang=lang)
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.Forbidden:
            await ctx.respond("❌ У меня нет прав для снятия мута с этого пользователя!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка в команде unmute: {e}")
            await ctx.respond("❌ Произошла ошибка при снятии мута.", ephemeral=True)

    # --- РАЗБАН ---
    @commands.command(name="unban", help="Разбанить пользователя по ID")
    @commands.has_permissions(administrator=True)
    async def prefix_unban(self, ctx: Context, user_id: int, *, reason: str = "Без причины"):
        if not ctx.author.guild_permissions.ban_members:
            await ctx.send("❌ У вас нет прав администратора!")
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            self.log_action("unban", str(ctx.author), str(user), reason)
            embed = discord.Embed(
                title="✅ Разбан",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.NotFound:
            await ctx.send("❌ Пользователь не найден!")
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для разбана этого пользователя!")
        except Exception as e:
            logger.error(f"Ошибка в команде unban: {e}")
            await ctx.send("❌ Произошла ошибка при разбане пользователя.")

    @commands.slash_command(name="unban", description="Разбанить пользователя по ID")
    async def unban_slash(self, ctx: discord.ApplicationContext, 
                        user_id: Option(int, "ID участника, которого нужно разбанить"),
                        reason: Option(str, "Причина действия (опционально)", default=None),
                        language: Option(str, "Язык", choices=["English", "Русский"], default="Русский")):
        lang = 'en' if language == "English" else 'ru'
        reason = reason or get_text('moderation.no_reason', lang)
        if not ctx.author.guild_permissions.ban_members:
            await ctx.respond("❌ У вас нет прав администратора!", ephemeral=True)
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            self.log_action("unban", str(ctx.author), str(user), reason, lang=lang)
            embed = discord.Embed(
                title="✅ Разбан",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_log_to_channel(ctx.guild, embed)
        except discord.NotFound:
            await ctx.respond("❌ Пользователь не найден!", ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("❌ У меня нет прав для разбана этого пользователя!", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка в команде unban: {e}")
            await ctx.respond("❌ Произошла ошибка при разбане пользователя.", ephemeral=True)

    @commands.slash_command(name="разбан", description="Разбанить пользователя по ID (синоним)")
    async def unban_slash_ru(self, ctx: discord.ApplicationContext, 
                        user_id: Option(int, "ID участника, которого нужно разбанить"),
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        await self.unban_slash.callback(self, ctx, user_id, reason)

    # --- VOICE МУТ ---
    @commands.command(name="voicemute", aliases=["вмут", "voice_mute", "мутмикро"], help="Мутит только микрофон пользователя в голосовом канале")
    async def prefix_voicemute(self, ctx: Context, member: discord.Member, *, reason: str = "Без причины"):
        if not (ctx.author.guild_permissions.mute_members or ctx.author.guild_permissions.moderate_members):
            await ctx.send("❌ У вас нет прав для voice mute этого пользователя!")
            return
        if not member.voice or not member.voice.channel:
            await ctx.send("❌ Пользователь не находится в голосовом канале!")
            return
        try:
            await member.edit(mute=True, reason=reason)
            self.log_action("voicemute", str(ctx.author), str(member), reason)
            embed = discord.Embed(
                title="🔇 Voice Мут",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "voicemute", member, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except Exception as e:
            logger.error(f"Ошибка в команде voicemute: {e}")
            await ctx.send("❌ Произошла ошибка при voice mute пользователя.")

    @commands.slash_command(name="voicemute", description="Мутит только микрофон пользователя в голосовом канале")
    async def voicemute_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        if not (ctx.author.guild_permissions.mute_members or ctx.author.guild_permissions.moderate_members):
            await ctx.respond("❌ У вас нет прав администратора!", ephemeral=True)
            return
        if not user.voice or not user.voice.channel:
            await ctx.respond("❌ Пользователь не находится в голосовом канале!", ephemeral=True)
            return
        try:
            await user.edit(mute=True, reason=reason)
            self.log_action("voicemute", str(ctx.author), str(user), reason)
            embed = discord.Embed(
                title="🔇 Voice Мут",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_moderation_embed(ctx, "voicemute", user, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except Exception as e:
            logger.error(f"Ошибка в команде voicemute: {e}")
            await ctx.respond("❌ Произошла ошибка при voice mute пользователя.", ephemeral=True)

    @commands.slash_command(name="вмут", description="Мутит только микрофон пользователя в голосовом канале (синоним)")
    async def voicemute_slash_ru(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        await self.voicemute_slash.callback(self, ctx, user, reason)

    # --- UNVOICEMUTE ---
    @commands.command(name="unvoicemute", aliases=["размутмикро", "unvmute"], help="Снять мут только микрофона в голосовом канале")
    async def prefix_unvoicemute(self, ctx: Context, member: discord.Member, *, reason: str = "Без причины"):
        if not (ctx.author.guild_permissions.mute_members or ctx.author.guild_permissions.moderate_members):
            await ctx.send("❌ У вас нет прав для unvoicemute этого пользователя!")
            return
        if not member.voice or not member.voice.channel:
            await ctx.send("❌ Пользователь не находится в голосовом канале!")
            return
        try:
            await member.edit(mute=False, reason=reason)
            self.log_action("unvoicemute", str(ctx.author), str(member), reason)
            embed = discord.Embed(
                title="🔊 Снятие voice мута",
                description=f"**Пользователь:** {member.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {member.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await msg.delete()
            await self.send_moderation_embed(ctx, "unvoicemute", member, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except Exception as e:
            logger.error(f"Ошибка в команде unvoicemute: {e}")
            await ctx.send("❌ Произошла ошибка при снятии voice mute пользователя.")

    @commands.slash_command(name="unvoicemute", description="Снять мут только микрофона в голосовом канале")
    async def unvoicemute_slash(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        if not (ctx.author.guild_permissions.mute_members or ctx.author.guild_permissions.moderate_members):
            await ctx.respond("❌ У вас нет прав администратора!", ephemeral=True)
            return
        if not user.voice or not user.voice.channel:
            await ctx.respond("❌ Пользователь не находится в голосовом канале!", ephemeral=True)
            return
        try:
            await user.edit(mute=False, reason=reason)
            self.log_action("unvoicemute", str(ctx.author), str(user), reason)
            embed = discord.Embed(
                title="🔊 Снятие voice мута",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"ID: {user.id}")
            embed.add_field(name='❓Вы не согласны с наказанием?', value='Обратитесь в поддержку, чтобы оправдать его! 🛑', inline=False)
            msg = await ctx.respond(embed=embed)
            await asyncio.sleep(5)
            await ctx.interaction.delete_original_response()
            await self.send_moderation_embed(ctx, "unvoicemute", user, reason)
            await self.send_log_to_channel(ctx.guild, embed)
        except Exception as e:
            logger.error(f"Ошибка в команде unvoicemute: {e}")
            await ctx.respond("❌ Произошла ошибка при снятии voice mute пользователя.", ephemeral=True)

    @commands.slash_command(name="размутмикро", description="Снять мут только микрофона (синоним)")
    async def unvoicemute_slash_ru(self, ctx: discord.ApplicationContext, 
                        user: discord.Member, 
                        reason: Option(str, "Причина действия (опционально)", default="Без причины")):
        await self.unvoicemute_slash.callback(self, ctx, user, reason)

    # --- СТАТИСТИКА СЕРВЕРА ---
    @commands.command(name="stats", help="Показать статистику сервера")
    async def prefix_stats(self, ctx: Context):
        """Показать статистику сервера"""
        try:
            guild = ctx.guild
            
            # Подсчитываем пользователей
            total_members = guild.member_count
            online_members = len([m for m in guild.members if m.status != discord.Status.offline])
            
            # Подсчитываем активные муты
            active_mutes = 0
            if MUTED_USERS_FILE.exists():
                with MUTED_USERS_FILE.open(encoding='utf-8') as f:
                    try:
                        mutes = json.load(f)
                        active_mutes = len(mutes)
                    except Exception:
                        active_mutes = 0
            
            # Подсчитываем запрещённые слова
            blocked_words = 0
            blocked_words_file = Path('discord_blocked_words_full.txt')
            if blocked_words_file.exists():
                with blocked_words_file.open(encoding='utf-8') as f:
                    blocked_words = len([line.strip() for line in f if line.strip()])
            
            # Подсчитываем муты за сегодня
            today_mutes = 0
            today = datetime.now().strftime('%Y-%m-%d')
            if BOT_ACTIONS_LOG.exists():
                with BOT_ACTIONS_LOG.open(encoding='utf-8') as f:
                    for line in f:
                        if today in line and '[MUTE]' in line:
                            today_mutes += 1
            
            # Создаём статистику
            stats = {
                'total_users': total_members,
                'online_users': online_members,
                'total_messages': 0,  # Пока не отслеживаем
                'mutes_today': today_mutes,
                'words_blocked': blocked_words,
                'active_mutes': active_mutes
            }
            
            # Больше не сохраняем для веб-панели; выводим только в Discord
            
            # Создаём embed
            embed = discord.Embed(
                title="📊 Статистика сервера",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👥 Пользователи", 
                value=f"**Всего:** {total_members}\n**Онлайн:** {online_members}", 
                inline=True
            )
            embed.add_field(
                name="🔇 Муты", 
                value=f"**Активных:** {active_mutes}\n**Сегодня:** {today_mutes}", 
                inline=True
            )
            embed.add_field(
                name="🛡️ Защита", 
                value=f"**Запрещённых слов:** {blocked_words}", 
                inline=True
            )
            
            embed.set_footer(text=f"Обновлено: {datetime.now().strftime('%H:%M:%S')}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Ошибка в команде stats: {e}")
            await ctx.send("❌ Произошла ошибка при получении статистики.")

    # Удаляем/комментируем слэш-команду stats
    # @commands.slash_command(name="stats", description="Показать статистику сервера", guild_ids=[1138780579312185425])
    # async def stats_slash(self, ctx: discord.ApplicationContext):
    #     """Показать статистику сервера"""
    #     await self.prefix_stats(ctx)

    # --- СИНХРОНИЗАЦИЯ КОМАНД ---
    # Удаляем/комментируем слэш-команду sync
    # @commands.slash_command(name="sync", description="Синхронизировать слэш-команды", guild_ids=[1138780579312185425])
    # async def sync_commands(self, ctx: discord.ApplicationContext):
    #     """Синхронизировать слэш-команды с Discord"""
    #     if not has_any_role(ctx.author, config.FULL_MOD_ROLE_IDS):
    #         await ctx.respond("❌ У вас нет прав администратора!", ephemeral=True)
    #         return
    #     try:
    #         await ctx.respond("🔄 Синхронизация команд...", ephemeral=True)
    #         synced = await self.bot.sync_commands()
    #         await ctx.edit(content=f"✅ Синхронизировано {len(synced)} команд!")
    #     except Exception as e:
    #         await ctx.edit(content=f"❌ Ошибка синхронизации: {e}")

async def setup(bot):
    await bot.add_cog(ModerationCog(bot)) 