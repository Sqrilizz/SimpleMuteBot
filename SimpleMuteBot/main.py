import os
import discord
from discord.ext import commands
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Union
from pathlib import Path
import json
import config

# Load configuration
DISCORD_TOKEN = getattr(config, 'DISCORD_TOKEN', None)
BOT_PREFIX = getattr(config, 'BOT_PREFIX', '!')
MUTED_ROLE_NAME = getattr(config, 'MUTED_ROLE_NAME', 'Muted')

# Constants
DEFAULT_MUTE_DURATION = timedelta(minutes=5)
CONFIG_DIR = Path('config')
DATA_FILE = CONFIG_DIR / 'muted_users.json'

# Setup logging
def setup_logging() -> logging.Logger:
    """Configure logging for the bot."""
    CONFIG_DIR.mkdir(exist_ok=True)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger('discord_bot')
    logger.setLevel(logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(CONFIG_DIR / 'bot.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# Конфигурация бота
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=BOT_PREFIX,
    intents=intents,
    help_command=None
)

# Вспомогательные функции

def parse_duration(duration_str: str) -> timedelta:
    """
    Parse duration string into timedelta.
    
    Args:
        duration_str: String representing duration (e.g., '30m', '2h', '1d', '30мин', '2ч', '1д')
        
    Returns:
        timedelta: Parsed duration
        
    Raises:
        ValueError: If duration format is invalid
    """
    if not duration_str:
        return DEFAULT_MUTE_DURATION
        
    duration_str = duration_str.strip().lower()
    
    # Time units mapping
    TIME_UNITS = {
        # English
        'm': 'minutes', 'min': 'minutes', 'mins': 'minutes', 'minute': 'minutes', 'minutes': 'minutes',
        'h': 'hours', 'hr': 'hours', 'hrs': 'hours', 'hour': 'hours', 'hours': 'hours',
        'd': 'days', 'day': 'days', 'days': 'days',
        'w': 'weeks', 'wk': 'weeks', 'wks': 'weeks', 'week': 'weeks', 'weeks': 'weeks',
        # Russian
        'мин': 'minutes', 'минута': 'minutes', 'минуты': 'minutes', 'минут': 'minutes',
        'ч': 'hours', 'час': 'hours', 'часа': 'hours', 'часов': 'hours',
        'д': 'days', 'день': 'days', 'дня': 'days', 'дней': 'days',
        'н': 'weeks', 'неделя': 'weeks', 'недели': 'weeks', 'недель': 'weeks'
    }
    
    # Try to match time units
    for unit, full_unit in TIME_UNITS.items():
        if duration_str.endswith(unit):
            try:
                value_str = duration_str[:-len(unit)].strip()
                value = int(value_str)
                if value <= 0:
                    raise ValueError(f"Duration must be positive: {duration_str}")
                return timedelta(**{full_unit: value})
            except ValueError as e:
                logger.error(f"Failed to parse duration '{duration_str}': {e}")
                raise ValueError(f"Invalid duration format: {duration_str}")
    
    # Try as minutes if no unit specified
    try:
        value = int(duration_str)
        if value <= 0:
            raise ValueError(f"Duration must be positive: {duration_str}")
        return timedelta(minutes=value)
    except ValueError:
        raise ValueError(f"Invalid duration format: {duration_str}")

def format_duration(duration: timedelta) -> str:
    """
    Format timedelta into a human-readable string in Russian.
    
    Args:
        duration: Time duration to format
        
    Returns:
        str: Formatted duration string
    """
    total_seconds = int(duration.total_seconds())
    
    if total_seconds < 60:
        seconds = total_seconds
        if seconds == 1:
            return "1 секунду"
        elif 2 <= seconds <= 4 or (seconds > 20 and seconds % 10 in (2, 3, 4)):
            return f"{seconds} секунды"
        else:
            return f"{seconds} секунд"
            
    elif total_seconds < 3600:  # Less than 1 hour
        minutes = total_seconds // 60
        if minutes == 1:
            return "1 минуту"
        elif 2 <= minutes <= 4 or (minutes > 20 and minutes % 10 in (2, 3, 4)):
            return f"{minutes} минуты"
        else:
            return f"{minutes} минут"
            
    elif total_seconds < 86400:  # Less than 1 day
        hours = total_seconds // 3600
        if hours == 1:
            return "1 час"
        elif 2 <= hours <= 4 or (hours > 20 and hours % 10 in (2, 3, 4)):
            return f"{hours} часа"
        else:
            return f"{hours} часов"
            
    else:  # Days or more
        days = total_seconds // 86400
        if days % 10 == 1 and days % 100 != 11:
            return f"{days} день"
        elif 2 <= days % 10 <= 4 and (days % 100 < 10 or days % 100 >= 20):
            return f"{days} дня"
        else:
            return f"{days} дней"

async def setup_hook() -> None:
    """Setup hook for the bot."""
    # Load cogs
    for filename in os.listdir("cogs"):
        if filename.endswith(".py") and not filename.startswith("_"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                logger.info(f"Loaded cog: {filename}")
            except Exception as e:
                logger.error(f"Failed to load cog {filename}: {e}")
    
    # Sync application commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

@bot.event
async def on_ready() -> None:
    """Called when the bot is ready."""
    # Set bot presence
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{len(bot.guilds)} servers | {BOT_PREFIX}help"
    )
    await bot.change_presence(activity=activity)
    
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    logger.info(f"Prefix: {BOT_PREFIX}")
    
    # Ensure muted role exists in all guilds
    for guild in bot.guilds:
        await ensure_muted_role(guild)
        
    logger.info("Bot is ready!")

async def ensure_muted_role(guild: discord.Guild) -> Optional[discord.Role]:
    """Ensure the muted role exists in the guild."""
    # Check if role already exists
    muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
    if muted_role:
        return muted_role
        
    # Create the role if it doesn't exist
    try:
        logger.info(f"Creating muted role in {guild.name}")
        muted_role = await guild.create_role(
            name=MUTED_ROLE_NAME,
            reason="Creating muted role for moderation"
        )
        
        # Set up permissions
        for channel in guild.channels:
            try:
                await channel.set_permissions(
                    muted_role,
                    send_messages=False,
                    speak=False,
                    add_reactions=False,
                    connect=False
                )
            except discord.Forbidden:
                logger.warning(f"Missing permissions to update {channel.name}")
            except Exception as e:
                logger.error(f"Error updating channel {channel.name}: {e}")
                
        return muted_role
    except discord.Forbidden:
        logger.error(f"Missing permissions to create muted role in {guild.name}")
        return None
    except Exception as e:
        logger.error(f"Error creating muted role in {guild.name}: {e}")
        return None

@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages."""
    # Ignore messages from bots
    if message.author.bot:
        return
        
    # Log command usage
    if message.content.startswith(BOT_PREFIX):
        logger.info(
            f"Command from {message.author} (ID: {message.author.id}) in "
            f"{message.guild.name if message.guild else 'DM'}/"
            f"{message.channel.name if hasattr(message.channel, 'name') else 'DM'}: "
            f"{message.content}"
        )
    
    # Process commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Handle command errors."""
    if hasattr(ctx.command, 'on_error') or (ctx.command and hasattr(ctx.command, 'on_error')):
        return
        
    error = getattr(error, 'original', error)
    
    # Ignore these errors
    ignored = (commands.CommandNotFound, commands.DisabledCommand)
    if isinstance(error, ignored):
        return
        
    # Handle specific errors
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас недостаточно прав для выполнения этой команды.")
    elif isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(f"`{perm}`" for perm in error.missing_permissions)
        await ctx.send(f"❌ У бота недостаточно прав. Необходимы: {missing}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен обязательный аргумент: `{error.param.name}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Неверный аргумент. Проверьте правильность ввода.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Эта команда на перезарядке. Попробуйте через {error.retry_after:.1f} сек.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ Эта команда недоступна в личных сообщениях.")
    elif isinstance(error, commands.PrivateMessageOnly):
        await ctx.send("❌ Эта команда работает только в личных сообщениях.")
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ Эта команда доступна только владельцу бота.")
    else:
        # Log unexpected errors
        logger.error(f"Error in command '{ctx.command}': {error}", exc_info=error)
        await ctx.send("❌ Произошла непредвиденная ошибка. Пожалуйста, сообщите об этом администратору.")

@bot.hybrid_command(
    name="mute",
    description="Заглушить пользователя на указанное время"
)
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def mute(
    ctx: commands.Context,
    member: discord.Member,
    duration: str,
    *,
    reason: str = "Не указана"
) -> None:
    """
    Заглушить пользователя на указанное время.
    
    Параметры:
    member: Пользователь, которого нужно заглушить
    duration: Длительность мута (например: 30м, 2ч, 1д)
    reason: Причина мута (по умолчанию: "Не указана")
    """
    # Prevent muting yourself or the bot
    if member == ctx.author:
        await ctx.send("❌ Вы не можете заглушить самого себя!")
        return
    if member == ctx.guild.me:
        await ctx.send("❌ Я не могу заглушить сам себя!")
        return
    
    # Check if the target has higher role
    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        await ctx.send("❌ Вы не можете заглушить пользователя с ролью выше или равной вашей!")
        return
    
    try:
        # Parse duration
        mute_duration = parse_duration(duration)
        
        # Get or create muted role
        muted_role = await ensure_muted_role(ctx.guild)
        if not muted_role:
            await ctx.send("❌ Не удалось найти или создать роль для мута.")
            return
            
        # Add muted role
        await member.add_roles(muted_role, reason=f"Мут от {ctx.author}: {reason}")
        
        # Send confirmation
        embed = discord.Embed(
            title="🔇 Пользователь заглушен",
            description=f"{member.mention} был успешно заглушен.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
        embed.add_field(name="Длительность", value=format_duration(mute_duration), inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        
        await ctx.send(embed=embed)
        logger.info(f"User {member} (ID: {member.id}) was muted by {ctx.author} (ID: {ctx.author.id}) for {mute_duration}")
        
        # Schedule unmute
        await schedule_unmute(member, mute_duration, reason)
        
    except ValueError as e:
        await ctx.send(f"❌ Ошибка: {e}")
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав для выдачи роли мута.")
    except Exception as e:
        logger.error(f"Error muting user: {e}", exc_info=True)
        await ctx.send("❌ Произошла ошибка при выдаче мута.")

@bot.hybrid_command(
    name="unmute",
    description="Снять мут с пользователя"
)
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def unmute(
    ctx: commands.Context,
    member: discord.Member,
    *,
    reason: str = "Не указана"
) -> None:
    """
    Снять мут с пользователя.
    
    Параметры:
    member: Пользователь, с которого нужно снять мут
    reason: Причина снятия мута (по умолчанию: "Не указана")
    """
    muted_role = discord.utils.get(ctx.guild.roles, name=MUTED_ROLE_NAME)
    if not muted_role or muted_role not in member.roles:
        await ctx.send("❌ Этот пользователь не заглушен.")
        return
        
    try:
        # Remove muted role
        await member.remove_roles(muted_role, reason=f"Размут от {ctx.author}: {reason}")
        
        # Send confirmation
        embed = discord.Embed(
            title="🔊 С пользователя снят мут",
            description=f"С {member.mention} был снят мут.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text=f"ID: {member.id}")
        
        await ctx.send(embed=embed)
        logger.info(f"User {member} (ID: {member.id}) was unmuted by {ctx.author} (ID: {ctx.author.id})")
        
        # Remove from scheduled unmutes
        await remove_scheduled_unmute(member.id)
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав для снятия роли мута.")
    except Exception as e:
        logger.error(f"Error unmuting user: {e}", exc_info=True)
        await ctx.send("❌ Произошла ошибка при снятии мута.")

@bot.hybrid_command(
    name="ping",
    description="Проверка задержки бота"
)
async def ping(ctx: commands.Context) -> None:
    """Показать задержку бота."""
    latency = round(bot.latency * 1000)  # Convert to ms
    
    embed = discord.Embed(
        title="🏓 Понг!",
        description=f"Задержка бота: {latency}мс",
        color=discord.Color.blue()
    )
    
    await ctx.send(embed=embed)
    
    # Log command usage
    logger.info(f"Ping command used by {ctx.author} (ID: {ctx.author.id}) - Latency: {latency}ms")

# Load environment variables from .env if it exists
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("Loaded environment variables from .env file")

# Main entry point
if __name__ == "__main__":
    # Validate token
    if not DISCORD_TOKEN:
        logger.error("Discord token not found! Please set DISCORD_TOKEN in config.py or .env file.")
        exit(1)
    
    # Set up event loop
    import asyncio
    
    async def main():
        async with bot:
            # Set up the bot
            await setup_hook()
            
            # Start the bot
            try:
                await bot.start(DISCORD_TOKEN)
            except discord.LoginFailure:
                logger.error("Failed to log in. Please check your token.")
                exit(1)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot is shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Bot has shut down.")
        # Close any resources here if needed