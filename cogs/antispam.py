import discord
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from main import format_duration
import config
import asyncio
from collections import defaultdict, deque
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Список запрещённых слов (загружается из файла)
BLOCKED_WORDS_FILE = Path('discord_blocked_words_full.txt')
BLOCKED_WORDS = []
try:
    with BLOCKED_WORDS_FILE.open(encoding='utf-8') as f:
        BLOCKED_WORDS = [line.strip().lower() for line in f if line.strip()]
except FileNotFoundError:
    BLOCKED_WORDS = []

# Параметры антиспама
SPAM_THRESHOLD = 5      # сообщений
SPAM_WINDOW = 10        # секунд
MENTION_SPAM_THRESHOLD = 5  # упоминаний
MENTION_SPAM_WINDOW = 10    # секунд
EMOJI_SPAM_THRESHOLD = 10   # эмодзи
EMOJI_SPAM_WINDOW = 10      # секунд

# Параметры анти-nuke
NUKE_ACTION_THRESHOLD = 3    # действий
NUKE_ACTION_WINDOW = 30      # секунд
NUKE_ALERT_THRESHOLD = 2     # действий для алерта

class AntiSpamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Белый список ботов (не трогаем их вебхуки)
        self.whitelisted_bots = {
            536991182035746816,  # Замените на ID бота Wick
        }
        
        # Антиспам для всех пользователей
        self.spam_history = defaultdict(lambda: deque(maxlen=SPAM_THRESHOLD))
        self.mention_spam_history = defaultdict(lambda: deque(maxlen=MENTION_SPAM_THRESHOLD))
        self.emoji_spam_history = defaultdict(lambda: deque(maxlen=EMOJI_SPAM_THRESHOLD))
        
        # Анти-nuke для администраторов
        self.nuke_history = defaultdict(lambda: deque(maxlen=NUKE_ACTION_THRESHOLD))
        self.nuke_alerts = set()
        
        # Временные муты
        self.temp_mutes = {}
        
        # Защита от спама логов
        self.processed_webhooks = set()
        self.webhook_cooldown = 60  # секунд
        self.notification_cooldown = {}  # Для защиты от спама уведомлений
        self.notification_delay = 30  # секунд между уведомлениями
        
        # Загружаем настройки
        self.load_settings()

    # === Управление запрещёнными словами (команды) ===
    @commands.command(name="blocked", help="Показать запрещённые слова (первые 50)")
    async def cmd_blocked_list(self, ctx):
        words = []
        if BLOCKED_WORDS_FILE.exists():
            with BLOCKED_WORDS_FILE.open(encoding='utf-8') as f:
                words = [line.strip() for line in f if line.strip()]
        if not words:
            await ctx.send("Список пуст.")
            return
        preview = words[:50]
        content = "\n".join(f"- {w}" for w in preview)
        more = f"\n… и ещё {len(words)-50}" if len(words) > 50 else ""
        await ctx.send(f"Всего слов: {len(words)}\n{content}{more}")

    @commands.command(name="addword", help="Добавить слово в блок-лист")
    @commands.has_permissions(administrator=True)
    async def cmd_add_word(self, ctx, *, word: str):
        word = (word or "").strip().lower()
        if not word:
            await ctx.send("Укажите слово.")
            return
        existing = set()
        if BLOCKED_WORDS_FILE.exists():
            with BLOCKED_WORDS_FILE.open(encoding='utf-8') as f:
                existing = set(line.strip().lower() for line in f if line.strip())
        if word in existing:
            await ctx.send("Это слово уже есть в списке.")
            return
        with BLOCKED_WORDS_FILE.open('a', encoding='utf-8') as f:
            f.write(word + '\n')
        # Обновляем кэш
        existing.add(word)
        global BLOCKED_WORDS
        BLOCKED_WORDS = list(existing)
        await ctx.send(f"Добавлено: `{word}`")

    @commands.command(name="delword", help="Удалить слово из блок-листа")
    @commands.has_permissions(administrator=True)
    async def cmd_del_word(self, ctx, *, word: str):
        word = (word or "").strip().lower()
        if not word or not BLOCKED_WORDS_FILE.exists():
            await ctx.send("Слово не найдено или файл пуст.")
            return
        with BLOCKED_WORDS_FILE.open(encoding='utf-8') as f:
            words = [line.strip() for line in f if line.strip()]
        new_words = [w for w in words if w.lower() != word]
        if len(new_words) == len(words):
            await ctx.send("Такого слова нет в списке.")
            return
        with BLOCKED_WORDS_FILE.open('w', encoding='utf-8') as f:
            for w in new_words:
                f.write(w + '\n')
        # Обновляем кэш
        global BLOCKED_WORDS
        BLOCKED_WORDS = [w.lower() for w in new_words]
        await ctx.send(f"Удалено: `{word}`")

    def load_settings(self):
        """Загружает настройки из файла"""
        settings_file = Path('antispam_settings.json')
        if settings_file.exists():
            try:
                with settings_file.open(encoding='utf-8') as f:
                    settings = json.load(f)
                    global SPAM_THRESHOLD, SPAM_WINDOW, MENTION_SPAM_THRESHOLD, MENTION_SPAM_WINDOW
                    global EMOJI_SPAM_THRESHOLD, EMOJI_SPAM_WINDOW, NUKE_ACTION_THRESHOLD, NUKE_ACTION_WINDOW
                    SPAM_THRESHOLD = settings.get('spam_threshold', SPAM_THRESHOLD)
                    SPAM_WINDOW = settings.get('spam_window', SPAM_WINDOW)
                    MENTION_SPAM_THRESHOLD = settings.get('mention_spam_threshold', MENTION_SPAM_THRESHOLD)
                    MENTION_SPAM_WINDOW = settings.get('mention_spam_window', MENTION_SPAM_WINDOW)
                    EMOJI_SPAM_THRESHOLD = settings.get('emoji_spam_threshold', EMOJI_SPAM_THRESHOLD)
                    EMOJI_SPAM_WINDOW = settings.get('emoji_spam_window', EMOJI_SPAM_WINDOW)
                    NUKE_ACTION_THRESHOLD = settings.get('nuke_action_threshold', NUKE_ACTION_THRESHOLD)
                    NUKE_ACTION_WINDOW = settings.get('nuke_action_window', NUKE_ACTION_WINDOW)
            except Exception as e:
                logger.error(f"Ошибка загрузки настроек антиспама: {e}")

    def save_settings(self):
        """Сохраняет настройки в файл"""
        settings = {
            'spam_threshold': SPAM_THRESHOLD,
            'spam_window': SPAM_WINDOW,
            'mention_spam_threshold': MENTION_SPAM_THRESHOLD,
            'mention_spam_window': MENTION_SPAM_WINDOW,
            'emoji_spam_threshold': EMOJI_SPAM_THRESHOLD,
            'emoji_spam_window': EMOJI_SPAM_WINDOW,
            'nuke_action_threshold': NUKE_ACTION_THRESHOLD,
            'nuke_action_window': NUKE_ACTION_WINDOW
        }
        settings_file = Path('antispam_settings.json')
        with settings_file.open('w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    async def check_spam(self, message):
        """Проверяет сообщение на спам"""
        user_id = message.author.id
        now = datetime.now(timezone.utc).timestamp()
        
        # Проверка обычного спама
        spam_history = self.spam_history[user_id]
        spam_history.append(now)
        
        if len(spam_history) == SPAM_THRESHOLD and (now - spam_history[0]) <= SPAM_WINDOW:
            await self.handle_spam(message, "обычный спам")
            return True
        
        # Проверка спама упоминаний
        mentions = len(message.mentions) + len(message.role_mentions)
        if mentions > 0:
            mention_history = self.mention_spam_history[user_id]
            mention_history.append(now)
            
            if len(mention_history) == MENTION_SPAM_THRESHOLD and (now - mention_history[0]) <= MENTION_SPAM_WINDOW:
                await self.handle_spam(message, "спам упоминаниями")
                return True
        
        # Проверка спама эмодзи
        emoji_chars = '😀😃😄😁😆😅😂🤣😊😇🙂🙃😉😌😍🥰😘😗😙😚😋😛😝😜🤪🤨🧐🤓😎🤩🥳😏😒😞😔😟😕🙁☹️😣😖😫😩🥺😢😭😤😠😡🤬🤯😳🥵🥶😱😨😰😥😓🤗🤔🤭🤫🤥😶😐😑😯😦😧😮😲🥱😴🤤😪😵🤐🥴🤢🤮🤧😷🤒🤕🤑🤠💀👻👽👾🤖😺😸😹😻😼😽🙀😿😾'
        emoji_count = len([c for c in message.content if c in emoji_chars])
        if emoji_count > 5:
            emoji_history = self.emoji_spam_history[user_id]
            emoji_history.append(now)
            
            if len(emoji_history) == EMOJI_SPAM_THRESHOLD and (now - emoji_history[0]) <= EMOJI_SPAM_WINDOW:
                await self.handle_spam(message, "спам эмодзи")
                return True
        
        return False

    async def check_bot_webhook_spam(self, message):
        """Проверяет спам от ботов и вебхуков"""
        user_id = message.author.id
        now = datetime.now(timezone.utc).timestamp()
        
        # Для вебхуков - мгновенная реакция на любое сообщение
        if message.webhook_id:
            # Сразу удаляем вебхук при первом же сообщении
            await self.handle_webhook_spam(message)
            return True
        
        # Для ботов - используем историю
        bot_spam_history = self.spam_history.get(f"bot_{user_id}", deque(maxlen=3))
        self.spam_history[f"bot_{user_id}"] = bot_spam_history
        bot_spam_history.append(now)
        
        # Более строгие правила для ботов: 3 сообщения за 5 секунд
        if len(bot_spam_history) == 3 and (now - bot_spam_history[0]) <= 5:
            # Добавляем небольшую задержку, чтобы избежать rate limit
            await asyncio.sleep(0.5)
            await self.handle_bot_spam(message)
            return True
        
        return False

    async def handle_webhook_spam(self, message):
        """Обрабатывает спам от вебхуков"""
        webhook_id = message.webhook_id
        
        # Проверяем, не обрабатывали ли мы уже этот вебхук
        if webhook_id in self.processed_webhooks:
            return
        
        # Проверяем белый список ботов
        try:
            webhook_obj = await self.bot.fetch_webhook(webhook_id)
            if webhook_obj.user and webhook_obj.user.id in self.whitelisted_bots:
                logger.info(f"[AntiSpam] Вебхук {webhook_id} от белого списка бота {webhook_obj.user.name}, пропускаем")
                return
        except Exception as e:
            logger.debug(f"Не удалось проверить владельца вебхука {webhook_id}: {e}")
            # Продолжаем обработку, если не можем проверить
        
        try:
            # Удаляем сообщение (если оно ещё существует)
            try:
                await message.delete()
            except discord.NotFound:
                pass  # Не логируем, если сообщение уже удалено
            except discord.Forbidden:
                logger.warning(f"[AntiSpam] Нет прав на удаление сообщения от вебхука {webhook_id}")
            
            # Удаляем вебхук
            if webhook_id:
                try:
                    webhook_obj = await self.bot.fetch_webhook(webhook_id)
                    await webhook_obj.delete(reason="Антиспам: удаление спам-вебхука")
                    logger.info(f"[AntiSpam] Удалён вебхук {webhook_id} за спам")
                except discord.NotFound:
                    logger.info(f"[AntiSpam] Вебхук {webhook_id} уже удалён")
                except Exception as e:
                    logger.error(f"Ошибка удаления вебхука {webhook_id}: {e}")
            
            # Добавляем вебхук в обработанные
            self.processed_webhooks.add(webhook_id)
            
            # Уведомление (только один раз с кулдауном)
            if self.can_send_notification("webhook_spam"):
                admin_role_id = getattr(config, 'ADMIN_ALERT_ROLE_ID', None) or (getattr(config, 'TRUSTED_ROLE_IDS', None) or [None])[0]
                admin_ping = f'<@&{admin_role_id}>' if admin_role_id else None
                allowed_mentions = discord.AllowedMentions(roles=True)
                
                embed = discord.Embed(
                    title="🚫 Спам-вебхук удалён",
                    description=f"**Вебхук:** {webhook_id}\n**Канал:** {message.channel.mention}\n**Причина:** Спам",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                
                # Отправляем в канал текущей гильдии
                guild = message.guild
                if guild:
                    target_channel = guild.get_channel(getattr(config, 'ATTACK_ALERT_CHANNEL_ID', None)) or guild.get_channel(getattr(config, 'LOG_CHANNEL_ID', None))
                    if not target_channel:
                        for ch in guild.text_channels:
                            if ch.name.lower() in ['mod-logs', 'moderation-logs', 'logs', 'modlogs', 'audit-logs'] and ch.permissions_for(guild.me).send_messages:
                                target_channel = ch
                                break
                    if not target_channel and guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                        target_channel = guild.system_channel
                    if target_channel:
                        if admin_ping:
                            await target_channel.send(admin_ping, allowed_mentions=allowed_mentions)
                        await target_channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Ошибка обработки спама вебхука {webhook_id}: {e}")
        
        # Очищаем старые записи через минуту
        asyncio.create_task(self.cleanup_processed_webhooks())

    async def cleanup_processed_webhooks(self):
        """Очищает старые записи обработанных вебхуков"""
        await asyncio.sleep(self.webhook_cooldown)
        self.processed_webhooks.clear()
    
    def can_send_notification(self, notification_type):
        """Проверяет, можно ли отправить уведомление"""
        now = datetime.now(timezone.utc).timestamp()
        last_notification = self.notification_cooldown.get(notification_type, 0)
        
        if now - last_notification < self.notification_delay:
            return False
        
        self.notification_cooldown[notification_type] = now
        return True

    async def handle_bot_spam(self, message):
        """Обрабатывает спам от ботов"""
        bot_id = message.author.id
        
        # Проверяем, не обрабатывали ли мы уже этого бота
        if bot_id in self.processed_webhooks:  # Используем тот же механизм
            return
        
        try:
            # Удаляем сообщение (если оно ещё существует)
            try:
                await message.delete()
            except discord.NotFound:
                pass  # Не логируем, если сообщение уже удалено
            except discord.Forbidden:
                logger.warning(f"[AntiSpam] Нет прав на удаление сообщения от бота {bot_id}")
            
            # Баним или кикаем бота
            try:
                if message.guild.me.guild_permissions.ban_members:
                    await message.guild.ban(message.author, reason="Антиспам: спам-бот")
                    action = "забанен"
                elif message.guild.me.guild_permissions.kick_members:
                    await message.guild.kick(message.author, reason="Антиспам: спам-бот")
                    action = "кикнут"
                else:
                    action = "не удалось наказать (нет прав)"
            except discord.NotFound:
                logger.info(f"[AntiSpam] Бот {message.author} уже покинул сервер")
                action = "уже покинул сервер"
            except Exception as e:
                logger.error(f"Ошибка наказания бота {bot_id}: {e}")
                action = "ошибка наказания"
            
            # Добавляем бота в обработанные
            self.processed_webhooks.add(bot_id)
            
            # Уведомление (только один раз с кулдауном)
            if self.can_send_notification("bot_spam"):
                admin_role_id = getattr(config, 'ADMIN_ALERT_ROLE_ID', None) or (getattr(config, 'TRUSTED_ROLE_IDS', None) or [None])[0]
                admin_ping = f'<@&{admin_role_id}>' if admin_role_id else None
                allowed_mentions = discord.AllowedMentions(roles=True)
                
                embed = discord.Embed(
                    title="🤖 Спам-бот наказан",
                    description=f"**Бот:** {message.author.mention}\n**ID:** {message.author.id}\n**Действие:** {action}",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed.set_footer(text=f"Канал: {message.channel.name}")
                
                guild = message.guild
                if guild:
                    target_channel = guild.get_channel(getattr(config, 'ATTACK_ALERT_CHANNEL_ID', None)) or guild.get_channel(getattr(config, 'LOG_CHANNEL_ID', None))
                    if not target_channel:
                        for ch in guild.text_channels:
                            if ch.name.lower() in ['mod-logs', 'moderation-logs', 'logs', 'modlogs', 'audit-logs'] and ch.permissions_for(guild.me).send_messages:
                                target_channel = ch
                                break
                    if not target_channel and guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                        target_channel = guild.system_channel
                    if target_channel:
                        if admin_ping:
                            await target_channel.send(admin_ping, allowed_mentions=allowed_mentions)
                        await target_channel.send(embed=embed)
            
            logger.info(f"[AntiSpam] Бот {message.author} {action} за спам")
            
        except Exception as e:
            logger.error(f"Ошибка обработки спама бота {bot_id}: {e}")

    async def handle_spam(self, message, spam_type):
        """Обрабатывает обнаруженный спам"""
        try:
            # Удаляем сообщение
            await message.delete()
            
            # Временный мут на 5 минут
            duration = timedelta(minutes=5)
            until = datetime.now(timezone.utc) + duration
            
            try:
                await message.author.timeout(until, reason=f"Антиспам: {spam_type}")
            except discord.Forbidden:
                logger.warning(f"Нет прав на мут пользователя {message.author}")
            
            # Уведомление
            embed = discord.Embed(
                title="🚫 Антиспам",
                description=f"**Пользователь:** {message.author.mention}\n**Тип:** {spam_type}\n**Длительность:** 5 минут",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"ID: {message.author.id}")
            
            await message.channel.send(embed=embed, delete_after=10)
            
            # Логирование
            logger.info(f"[AntiSpam] {message.author} получил мут за {spam_type}")
            
        except discord.Forbidden:
            logger.warning("Нет прав на удаление сообщения")
        except Exception as e:
            logger.error(f"Ошибка обработки спама: {e}")

    async def check_nuke_actions(self, user_id, action_type):
        """Проверяет действия на подозрительную активность (анти-nuke)"""
        now = datetime.now(timezone.utc).timestamp()
        nuke_history = self.nuke_history[user_id]
        nuke_history.append((now, action_type))
        
        # Проверяем количество действий за окно времени
        recent_actions = [action for timestamp, action in nuke_history if (now - timestamp) <= NUKE_ACTION_WINDOW]
        
        if len(recent_actions) >= NUKE_ALERT_THRESHOLD:
            if user_id not in self.nuke_alerts:
                await self.send_nuke_alert(user_id, recent_actions)
                self.nuke_alerts.add(user_id)
                # Сброс алерта через 5 минут
                asyncio.create_task(self.reset_nuke_alert(user_id))

    async def send_nuke_alert(self, user_id, actions):
        """Отправляет алерт о подозрительной активности"""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                return
            
            embed = discord.Embed(
                title="🚨 Подозрительная активность!",
                description=(
                    f"**Пользователь:** {user.mention}\n"
                    f"**ID:** {user_id}\n"
                    f"**Действия:** {', '.join(actions)}\n\n"
                    f"**Возможная попытка nuke! Проверьте права пользователя!**"
                ),
                color=discord.Color.dark_red(),
                timestamp=datetime.now()
            )
            embed.set_footer(text="AntiNuke Protection")
            
            # Отправляем в канал алертов с пингом (с кулдауном)
            if self.can_send_notification("nuke_alert"):
                admin_role_id = getattr(config, 'ADMIN_ALERT_ROLE_ID', None) or (getattr(config, 'TRUSTED_ROLE_IDS', None) or [None])[0]
                admin_ping = f'<@&{admin_role_id}>' if admin_role_id else None
                allowed_mentions = discord.AllowedMentions(roles=True)
                
                # Ищем гильдию, где есть этот пользователь
                for guild in self.bot.guilds:
                    member = guild.get_member(user_id)
                    if member:
                        target_channel = guild.get_channel(getattr(config, 'ATTACK_ALERT_CHANNEL_ID', None)) or guild.get_channel(getattr(config, 'LOG_CHANNEL_ID', None))
                        if not target_channel:
                            for ch in guild.text_channels:
                                if ch.name.lower() in ['mod-logs', 'moderation-logs', 'logs', 'modlogs', 'audit-logs'] and ch.permissions_for(guild.me).send_messages:
                                    target_channel = ch
                                    break
                        if not target_channel and guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                            target_channel = guild.system_channel
                        if target_channel:
                            if admin_ping:
                                await target_channel.send(admin_ping, allowed_mentions=allowed_mentions)
                            await target_channel.send(embed=embed)
                            break
                        
        except Exception as e:
            logger.error(f"Ошибка отправки nuke алерта: {e}")

    async def reset_nuke_alert(self, user_id):
        """Сбрасывает алерт nuke через 5 минут"""
        await asyncio.sleep(300)  # 5 минут
        self.nuke_alerts.discard(user_id)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Обработчик всех сообщений"""
        if message.author == self.bot.user:
            return
        
        # Проверяем, что сообщение ещё существует
        try:
            # Проверяем доступность сообщения
            await message.channel.fetch_message(message.id)
        except discord.NotFound:
            logger.info(f"[AntiSpam] Сообщение {message.id} уже удалено, пропускаем")
            return
        except Exception:
            # Если не можем проверить, продолжаем обработку
            pass
        
        # Проверка запрещённых слов
        content = message.content.lower()
        for word in BLOCKED_WORDS:
            if word in content:
                try:
                    await message.delete()
                    
                    # Если это вебхук - удаляем его
                    if message.webhook_id:
                        await self.handle_webhook_spam(message)
                        return
                    # Если это бот - баним/кикаем
                    elif message.author.bot:
                        await self.handle_bot_spam(message)
                        return
                    # Обычный пользователь
                    else:
                        await message.channel.send(
                            f"❌ {message.author.mention}, ваше сообщение было удалено (запрещённое слово)",
                            delete_after=5
                        )
                    
                    logger.info(f"[AntiSpam] Удалено сообщение от {message.author}: {message.content}")
                except discord.Forbidden:
                    logger.warning("[AntiSpam] Нет прав на удаление сообщений.")
                except Exception as e:
                    logger.error(f"[AntiSpam] Ошибка: {e}")
                return
        
        # Проверка спама только для обычных пользователей
        if not message.author.bot and not message.webhook_id:
            await self.check_spam(message)
        # Для ботов - отдельная обработка
        elif message.author.bot:
            await self.check_bot_webhook_spam(message)
        # Для вебхуков - мгновенная реакция
        elif message.webhook_id:
            await self.handle_webhook_spam(message)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Отслеживает баны"""
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
            if entry.user.id != self.bot.user.id:
                await self.check_nuke_actions(entry.user.id, "ban")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Отслеживает кики"""
        async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=1):
            if entry.user.id != self.bot.user.id:
                await self.check_nuke_actions(entry.user.id, "kick")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Отслеживает удаление каналов"""
        async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
            if entry.user.id != self.bot.user.id:
                await self.check_nuke_actions(entry.user.id, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """Отслеживает удаление ролей"""
        async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
            if entry.user.id != self.bot.user.id:
                await self.check_nuke_actions(entry.user.id, "role_delete")

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        """Отслеживает удаление эмодзи"""
        if len(before) > len(after):
            async for entry in guild.audit_logs(action=discord.AuditLogAction.emoji_delete, limit=1):
                if entry.user.id != self.bot.user.id:
                    await self.check_nuke_actions(entry.user.id, "emoji_delete")

    # Команды управления антиспамом
    @commands.command(name="antispam", help="Настройки антиспама")
    async def antispam_settings(self, ctx):
        """Показывает текущие настройки антиспама"""
        embed = discord.Embed(
            title="⚙️ Настройки антиспама",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📝 Обычный спам",
            value=f"**Порог:** {SPAM_THRESHOLD} сообщений\n**Окно:** {SPAM_WINDOW} сек",
            inline=True
        )
        embed.add_field(
            name="📢 Спам упоминаниями",
            value=f"**Порог:** {MENTION_SPAM_THRESHOLD} упоминаний\n**Окно:** {MENTION_SPAM_WINDOW} сек",
            inline=True
        )
        embed.add_field(
            name="😀 Спам эмодзи",
            value=f"**Порог:** {EMOJI_SPAM_THRESHOLD} эмодзи\n**Окно:** {EMOJI_SPAM_WINDOW} сек",
            inline=True
        )
        embed.add_field(
            name="🛡️ Анти-nuke",
            value=f"**Порог:** {NUKE_ACTION_THRESHOLD} действий\n**Окно:** {NUKE_ACTION_WINDOW} сек",
            inline=True
        )
        
        await ctx.send(embed=embed)

    @commands.command(name="setspam", help="Изменить настройки антиспама")
    async def set_spam_settings(self, ctx, setting: str, value: int):
        """Изменяет настройки антиспама"""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ У вас нет прав администратора!")
            return
        
        global SPAM_THRESHOLD, SPAM_WINDOW, MENTION_SPAM_THRESHOLD, MENTION_SPAM_WINDOW
        global EMOJI_SPAM_THRESHOLD, EMOJI_SPAM_WINDOW, NUKE_ACTION_THRESHOLD, NUKE_ACTION_WINDOW
        
        setting = setting.lower()
        if setting == "spam_threshold":
            SPAM_THRESHOLD = value
        elif setting == "spam_window":
            SPAM_WINDOW = value
        elif setting == "mention_threshold":
            MENTION_SPAM_THRESHOLD = value
        elif setting == "mention_window":
            MENTION_SPAM_WINDOW = value
        elif setting == "emoji_threshold":
            EMOJI_SPAM_THRESHOLD = value
        elif setting == "emoji_window":
            EMOJI_SPAM_WINDOW = value
        elif setting == "nuke_threshold":
            NUKE_ACTION_THRESHOLD = value
        elif setting == "nuke_window":
            NUKE_ACTION_WINDOW = value
        else:
            await ctx.send("❌ Неизвестная настройка!")
            return
        
        self.save_settings()
        await ctx.send(f"✅ Настройка `{setting}` изменена на `{value}`")

    @commands.command(name="delwebhook", help="Удалить вебхук по ID")
    async def delete_webhook(self, ctx, webhook_id: int):
        """Удаляет вебхук по ID"""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ У вас нет прав администратора!")
            return
        
        try:
            webhook = await self.bot.fetch_webhook(webhook_id)
            await webhook.delete(reason=f"Удалён администратором {ctx.author}")
            
            embed = discord.Embed(
                title="🚫 Вебхук удалён",
                description=f"**Вебхук:** {webhook_id}\n**Администратор:** {ctx.author.mention}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            await ctx.send(embed=embed)
            logger.info(f"[AntiSpam] Вебхук {webhook_id} удалён администратором {ctx.author}")
            
        except discord.NotFound:
            await ctx.send("❌ Вебхук не найден!")
        except Exception as e:
            await ctx.send(f"❌ Ошибка удаления вебхука: {e}")
            logger.error(f"Ошибка удаления вебхука: {e}")

    @commands.command(name="whitelist", help="Управление белым списком ботов")
    async def manage_whitelist(self, ctx, action: str, bot_id: int = None):
        """Управляет белым списком ботов"""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ У вас нет прав администратора!")
            return
        
        action = action.lower()
        
        if action == "list":
            if not self.whitelisted_bots:
                await ctx.send("📋 Белый список пуст")
                return
            
            embed = discord.Embed(
                title="📋 Белый список ботов",
                color=discord.Color.green()
            )
            
            for bot_id in self.whitelisted_bots:
                try:
                    bot_user = await self.bot.fetch_user(bot_id)
                    embed.add_field(
                        name=f"🤖 {bot_user.name}",
                        value=f"ID: {bot_id}",
                        inline=True
                    )
                except:
                    embed.add_field(
                        name=f"🤖 Неизвестный бот",
                        value=f"ID: {bot_id}",
                        inline=True
                    )
            
            await ctx.send(embed=embed)
            
        elif action == "add" and bot_id:
            self.whitelisted_bots.add(bot_id)
            await ctx.send(f"✅ Бот {bot_id} добавлен в белый список")
            logger.info(f"[AntiSpam] Бот {bot_id} добавлен в белый список администратором {ctx.author}")
            
        elif action == "remove" and bot_id:
            if bot_id in self.whitelisted_bots:
                self.whitelisted_bots.remove(bot_id)
                await ctx.send(f"❌ Бот {bot_id} удалён из белого списка")
                logger.info(f"[AntiSpam] Бот {bot_id} удалён из белого списка администратором {ctx.author}")
            else:
                await ctx.send(f"❌ Бот {bot_id} не найден в белом списке")
                
        else:
            await ctx.send("❌ Использование: `!whitelist <list|add|remove> [bot_id]`")

async def setup(bot):
    await bot.add_cog(AntiSpamCog(bot)) 