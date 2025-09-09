"""
Telegram Bot Service - 基于python-telegram-bot库的完整集成服务
提供智能消息格式处理、错误恢复机制和高级功能支持
"""

import asyncio
import json
import time
import re
from typing import Optional, Dict, Any, List
from loguru import logger
import traceback

# python-telegram-bot库导入
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, TimedOut, NetworkError


class TelegramBotService:
    """基于python-telegram-bot的Telegram Bot服务类"""

    def __init__(self, bot_token: str):
        """
        初始化Telegram Bot服务

        Args:
            bot_token: Telegram Bot Token
        """
        self.bot_token = bot_token
        self.bot = Bot(token=bot_token)
        self.rate_limiter = TelegramRateLimiter()

        logger.info(f"初始化Telegram Bot服务: {bot_token[:10]}...")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        pass
    
    async def send_message(self, chat_id: int, text: str,
                          parse_mode: Optional[str] = None,
                          reply_markup: Optional[InlineKeyboardMarkup] = None,
                          disable_notification: bool = False) -> bool:
        """
        发送消息到Telegram

        Args:
            chat_id: 聊天ID
            text: 消息文本
            parse_mode: 解析模式 ('HTML', 'MarkdownV2', None)
            reply_markup: 内联键盘
            disable_notification: 是否静默发送

        Returns:
            bool: 发送是否成功
        """
        try:
            # 速率限制检查
            await self.rate_limiter.wait_if_needed()

            # 智能格式处理
            if parse_mode is None:
                return await self._send_with_smart_format(
                    chat_id, text, reply_markup, disable_notification
                )
            else:
                return await self._send_single_format(
                    chat_id, text, parse_mode, reply_markup, disable_notification
                )

        except Exception as e:
            logger.error(f"发送Telegram消息异常: {e}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return False
    
    async def _send_with_smart_format(self, chat_id: int, text: str,
                                    reply_markup: Optional[InlineKeyboardMarkup] = None,
                                    disable_notification: bool = False) -> bool:
        """智能格式发送 - 自动降级处理"""

        # 检测文本格式
        has_html = self._detect_html(text)
        has_markdown = self._detect_markdown(text)

        # 检查是否包含MarkdownV2特殊字符但未正确转义
        has_unescaped_chars = self._has_unescaped_markdown_chars(text)

        # 确定尝试顺序
        if has_html:
            formats_to_try = [ParseMode.HTML, None]
        elif has_markdown and not has_unescaped_chars:
            formats_to_try = [ParseMode.MARKDOWN_V2, ParseMode.HTML, None]
        else:
            formats_to_try = [None]  # 直接使用纯文本

        # 逐个尝试格式
        for parse_mode in formats_to_try:
            try:
                success = await self._send_single_format(
                    chat_id, text, parse_mode, reply_markup, disable_notification
                )
                if success:
                    logger.debug(f"消息发送成功，使用格式: {parse_mode or '纯文本'}")
                    return True

            except BadRequest as e:
                if "parse" in str(e).lower():
                    logger.debug(f"格式 {parse_mode} 解析失败，尝试下一个: {e}")
                    continue
                else:
                    logger.error(f"发送失败: {e}")
                    return False
            except Exception as e:
                logger.debug(f"格式 {parse_mode} 发送失败: {e}")
                continue

        logger.error(f"所有格式都发送失败: {chat_id}")
        return False
    
    async def _send_single_format(self, chat_id: int, text: str,
                                parse_mode: Optional[str] = None,
                                reply_markup: Optional[InlineKeyboardMarkup] = None,
                                disable_notification: bool = False) -> bool:
        """使用单一格式发送消息"""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=disable_notification
            )
            logger.debug(f"PTB消息发送成功: {chat_id}")
            return True

        except BadRequest as e:
            logger.error(f"Telegram API请求错误: {e}")

            # 特殊错误处理
            error_desc = str(e)
            if 'parse entities' in error_desc.lower():
                logger.warning("检测到实体解析错误，建议使用纯文本模式")
            elif 'message is too long' in error_desc.lower():
                logger.warning("消息过长，需要分割发送")

            return False

        except TimedOut as e:
            logger.error(f"Telegram API超时: {e}")
            return False
        except NetworkError as e:
            logger.error(f"Telegram网络错误: {e}")
            return False
        except TelegramError as e:
            logger.error(f"Telegram通用错误: {e}")
            return False
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False
    
    async def send_message_with_buttons(self, chat_id: int, text: str,
                                      buttons: List[List[tuple]],
                                      parse_mode: Optional[str] = None) -> bool:
        """
        发送带内联键盘的消息

        Args:
            chat_id: 聊天ID
            text: 消息文本
            buttons: 按钮列表 [[(text, callback_data), ...], ...]
            parse_mode: 解析模式

        Returns:
            bool: 发送是否成功
        """
        try:
            keyboard = []
            for button_row in buttons:
                row = []
                for button_text, callback_data in button_row:
                    row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
                keyboard.append(row)

            reply_markup = InlineKeyboardMarkup(keyboard)
            return await self.send_message(chat_id, text, parse_mode, reply_markup)

        except Exception as e:
            logger.error(f"发送键盘消息异常: {e}")
            return False

    async def edit_message(self, chat_id: int, message_id: int,
                          new_text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> bool:
        """编辑消息"""
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=new_text,
                reply_markup=reply_markup
            )
            return True
        except Exception as e:
            logger.error(f"编辑消息失败: {e}")
            return False

    async def send_document(self, chat_id: int, document_path: str,
                           caption: str = "") -> bool:
        """发送文档"""
        try:
            with open(document_path, 'rb') as document:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"发送文档失败: {e}")
            return False
    
    def _detect_markdown(self, text: str) -> bool:
        """检测文本是否包含Markdown格式"""
        markdown_patterns = [
            r'\*\*.*?\*\*',  # 粗体
            r'\*.*?\*',      # 斜体
            r'`.*?`',        # 代码
            r'```.*?```',    # 代码块
            r'\[.*?\]\(.*?\)',  # 链接
        ]
        
        for pattern in markdown_patterns:
            if re.search(pattern, text, re.DOTALL):
                return True
        return False

    def _has_unescaped_markdown_chars(self, text: str) -> bool:
        """检测文本是否包含未转义的MarkdownV2特殊字符"""
        # MarkdownV2中需要转义的字符
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

        for char in special_chars:
            # 查找未转义的特殊字符（前面没有反斜杠）
            pattern = f'(?<!\\\\){re.escape(char)}'
            if re.search(pattern, text):
                return True
        return False

    def _detect_html(self, text: str) -> bool:
        """检测文本是否包含HTML格式"""
        html_patterns = [
            r'<b>.*?</b>',
            r'<i>.*?</i>',
            r'<code>.*?</code>',
            r'<pre>.*?</pre>',
            r'<a href=.*?>.*?</a>',
        ]
        
        for pattern in html_patterns:
            if re.search(pattern, text, re.DOTALL):
                return True
        return False


class TelegramRateLimiter:
    """Telegram API速率限制器"""
    
    def __init__(self, max_requests_per_second: int = 30):
        """
        初始化速率限制器
        
        Args:
            max_requests_per_second: 每秒最大请求数
        """
        self.max_requests = max_requests_per_second
        self.requests = []
        self.lock = asyncio.Lock()
    
    async def wait_if_needed(self):
        """如果需要，等待以遵守速率限制"""
        async with self.lock:
            now = time.time()
            
            # 清理过期的请求记录
            self.requests = [req_time for req_time in self.requests if now - req_time < 1.0]
            
            # 检查是否需要等待
            if len(self.requests) >= self.max_requests:
                wait_time = 1.0 - (now - self.requests[0])
                if wait_time > 0:
                    logger.debug(f"速率限制等待: {wait_time:.2f}秒")
                    await asyncio.sleep(wait_time)
            
            # 记录当前请求
            self.requests.append(now)


class TelegramBotManager:
    """Telegram Bot管理器 - 全局单例"""
    
    _instance = None
    _bots: Dict[str, TelegramBotService] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_bot(self, bot_token: str) -> TelegramBotService:
        """
        获取或创建Bot实例
        
        Args:
            bot_token: Bot Token
            
        Returns:
            TelegramBotService: Bot服务实例
        """
        if bot_token not in self._bots:
            self._bots[bot_token] = TelegramBotService(bot_token)
        
        return self._bots[bot_token]
    
    async def send_message(self, chat_id: int, text: str, 
                          bot_token: Optional[str] = None) -> bool:
        """
        便捷的消息发送方法
        
        Args:
            chat_id: 聊天ID
            text: 消息文本
            bot_token: Bot Token (如果为None，使用默认配置)
            
        Returns:
            bool: 发送是否成功
        """
        if not bot_token:
            # 从数据库获取默认配置
            bot_token = await self._get_default_bot_token()
            if not bot_token:
                logger.error("未找到可用的Bot Token")
                return False
        
        bot = await self.get_bot(bot_token)
        async with bot:
            return await bot.send_message(chat_id, text)
    
    async def _get_default_bot_token(self) -> Optional[str]:
        """从数据库获取默认Bot Token"""
        try:
            from db_manager import db_manager
            channels = db_manager.get_notification_channels()
            
            for channel in channels:
                if channel['type'] == 'telegram':
                    config = json.loads(channel['config'])
                    return config.get('bot_token')
            
            return None
        except Exception as e:
            logger.error(f"获取默认Bot Token失败: {e}")
            return None


# 全局管理器实例
telegram_bot_manager = TelegramBotManager()


# 便捷函数，用于向后兼容
async def send_telegram_message(chat_id: int, text: str, bot_token: Optional[str] = None) -> bool:
    """
    便捷的消息发送函数

    Args:
        chat_id: 聊天ID
        text: 消息文本
        bot_token: Bot Token (可选)

    Returns:
        bool: 发送是否成功
    """
    return await telegram_bot_manager.send_message(chat_id, text, bot_token)
