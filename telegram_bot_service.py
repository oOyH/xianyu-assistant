import asyncio
import time
import json
from typing import Dict, List, Optional, Any
from collections import defaultdict
import aiohttp
from loguru import logger
from db_manager import db_manager


class TelegramRateLimiter:
    """Telegram API频率限制器"""
    
    def __init__(self, max_requests_per_second: int = 30):
        """
        初始化频率限制器
        
        Args:
            max_requests_per_second: 每秒最大请求数，默认30（Telegram Bot API限制）
        """
        self.max_requests_per_second = max_requests_per_second
        self.requests = defaultdict(list)  # chat_id -> [timestamp, ...]
        self.global_requests = []  # 全局请求时间戳
        
    async def wait_if_needed(self, chat_id: int = None):
        """如果需要，等待以遵守频率限制"""
        current_time = time.time()
        
        # 清理过期的请求记录（1秒前的）
        self.global_requests = [
            req_time for req_time in self.global_requests 
            if current_time - req_time < 1.0
        ]
        
        if chat_id:
            self.requests[chat_id] = [
                req_time for req_time in self.requests[chat_id]
                if current_time - req_time < 1.0
            ]
        
        # 检查全局频率限制
        if len(self.global_requests) >= self.max_requests_per_second:
            wait_time = 1.0 - (current_time - self.global_requests[0])
            if wait_time > 0:
                logger.debug(f"全局频率限制，等待 {wait_time:.2f} 秒")
                await asyncio.sleep(wait_time)
        
        # 检查单个聊天的频率限制（每个聊天每秒最多1条消息）
        if chat_id and len(self.requests[chat_id]) >= 1:
            wait_time = 1.0 - (current_time - self.requests[chat_id][-1])
            if wait_time > 0:
                logger.debug(f"聊天 {chat_id} 频率限制，等待 {wait_time:.2f} 秒")
                await asyncio.sleep(wait_time)
        
        # 记录请求时间
        current_time = time.time()
        self.global_requests.append(current_time)
        if chat_id:
            self.requests[chat_id].append(current_time)


class TelegramBotService:
    """Telegram Bot服务管理类"""
    
    def __init__(self, bot_token: str):
        """
        初始化Telegram Bot服务
        
        Args:
            bot_token: Telegram Bot Token
        """
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.rate_limiter = TelegramRateLimiter()
        self.session = None
        self._bot_info = None
        
        logger.info(f"初始化Telegram Bot服务: {bot_token[:10]}...")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, method: str, data: Dict[str, Any] = None, 
                          chat_id: int = None, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        发送API请求到Telegram
        
        Args:
            method: API方法名
            data: 请求数据
            chat_id: 聊天ID（用于频率限制）
            max_retries: 最大重试次数
            
        Returns:
            API响应数据，失败返回None
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = f"{self.base_url}/{method}"
        
        for attempt in range(max_retries + 1):
            try:
                # 等待频率限制
                await self.rate_limiter.wait_if_needed(chat_id)
                
                timeout = aiohttp.ClientTimeout(total=10)
                async with self.session.post(url, json=data, timeout=timeout) as response:
                    response_data = await response.json()
                    
                    if response.status == 200 and response_data.get('ok'):
                        return response_data.get('result')
                    elif response.status == 429:  # Too Many Requests
                        retry_after = response_data.get('parameters', {}).get('retry_after', 1)
                        logger.warning(f"Telegram API频率限制，等待 {retry_after} 秒后重试")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"Telegram API请求失败: {response.status}, {response_data}")
                        if attempt < max_retries:
                            await asyncio.sleep(2 ** attempt)  # 指数退避
                            continue
                        return None
                        
            except asyncio.TimeoutError:
                logger.warning(f"Telegram API请求超时，尝试 {attempt + 1}/{max_retries + 1}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            except Exception as e:
                logger.error(f"Telegram API请求异常: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
        
        return None
    
    async def get_me(self) -> Optional[Dict[str, Any]]:
        """获取Bot信息"""
        if self._bot_info is None:
            self._bot_info = await self._make_request('getMe')
        return self._bot_info
    
    async def send_message(self, chat_id: int, text: str, parse_mode: str = None,
                          disable_web_page_preview: bool = True) -> bool:
        """
        发送消息
        
        Args:
            chat_id: 聊天ID
            text: 消息内容
            parse_mode: 解析模式（Markdown或HTML）
            disable_web_page_preview: 是否禁用网页预览
            
        Returns:
            发送成功返回True，失败返回False
        """
        try:
            data = {
                'chat_id': chat_id,
                'text': text,
                'disable_web_page_preview': disable_web_page_preview
            }

            # 只在parse_mode不为None时才添加该字段
            if parse_mode:
                data['parse_mode'] = parse_mode
            
            result = await self._make_request('sendMessage', data, chat_id)
            if result:
                logger.debug(f"消息发送成功: {chat_id}")
                return True
            else:
                logger.error(f"消息发送失败: {chat_id}")
                return False
                
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False
    
    async def set_webhook(self, webhook_url: str, secret_token: str = None) -> bool:
        """
        设置Webhook
        
        Args:
            webhook_url: Webhook URL
            secret_token: 可选的密钥令牌
            
        Returns:
            设置成功返回True，失败返回False
        """
        try:
            data = {
                'url': webhook_url,
                'allowed_updates': ['message', 'callback_query']
            }
            
            if secret_token:
                data['secret_token'] = secret_token
            
            result = await self._make_request('setWebhook', data)
            if result:
                logger.info(f"Webhook设置成功: {webhook_url}")
                return True
            else:
                logger.error(f"Webhook设置失败: {webhook_url}")
                return False
                
        except Exception as e:
            logger.error(f"设置Webhook异常: {e}")
            return False
    
    async def get_webhook_info(self) -> Optional[Dict[str, Any]]:
        """获取Webhook信息"""
        return await self._make_request('getWebhookInfo')
    
    async def delete_webhook(self) -> bool:
        """删除Webhook"""
        try:
            result = await self._make_request('deleteWebhook')
            if result:
                logger.info("Webhook删除成功")
                return True
            else:
                logger.error("Webhook删除失败")
                return False
        except Exception as e:
            logger.error(f"删除Webhook异常: {e}")
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            包含Bot状态信息的字典
        """
        try:
            bot_info = await self.get_me()
            webhook_info = await self.get_webhook_info()
            
            if bot_info:
                status = {
                    'status': 'healthy',
                    'bot_info': {
                        'id': bot_info.get('id'),
                        'username': bot_info.get('username'),
                        'first_name': bot_info.get('first_name')
                    },
                    'webhook_info': webhook_info,
                    'timestamp': time.time()
                }
            else:
                status = {
                    'status': 'unhealthy',
                    'error': 'Failed to get bot info',
                    'timestamp': time.time()
                }
            
            return status
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def validate_token_format(self) -> bool:
        """验证Token格式"""
        try:
            # Telegram Bot Token格式：数字:字符串
            if ':' not in self.bot_token:
                return False
            
            parts = self.bot_token.split(':')
            if len(parts) != 2:
                return False
            
            # 第一部分应该是数字（Bot ID）
            try:
                int(parts[0])
            except ValueError:
                return False
            
            # 第二部分应该是字符串（至少35个字符）
            if len(parts[1]) < 35:
                return False
            
            return True
            
        except Exception:
            return False


class TelegramBotManager:
    """Telegram Bot管理器，管理多个Bot实例"""
    
    def __init__(self):
        self.bots = {}  # chat_id -> TelegramBotService
        self.bot_configs = {}  # chat_id -> config
        
    async def get_or_create_bot(self, chat_id: int) -> Optional[TelegramBotService]:
        """获取或创建Bot实例"""
        try:
            if chat_id in self.bots:
                return self.bots[chat_id]
            
            # 从数据库获取配置
            channels = db_manager.get_notification_channels()
            telegram_channels = [ch for ch in channels if ch['type'] == 'telegram']
            
            for channel in telegram_channels:
                try:
                    config = json.loads(channel['config'])
                    if int(config.get('chat_id', 0)) == chat_id:
                        bot_token = config.get('bot_token')
                        if bot_token:
                            bot_service = TelegramBotService(bot_token)
                            if bot_service.validate_token_format():
                                self.bots[chat_id] = bot_service
                                self.bot_configs[chat_id] = config
                                logger.info(f"创建Bot实例: {chat_id}")
                                return bot_service
                            else:
                                logger.error(f"Bot Token格式无效: {chat_id}")
                except Exception as e:
                    logger.error(f"解析Bot配置失败: {e}")
                    continue
            
            logger.warning(f"未找到Chat ID {chat_id} 对应的Bot配置")
            return None
            
        except Exception as e:
            logger.error(f"获取或创建Bot实例失败: {e}")
            return None
    
    async def send_message(self, chat_id: int, text: str) -> bool:
        """发送消息到指定聊天"""
        bot = await self.get_or_create_bot(chat_id)
        if bot:
            return await bot.send_message(chat_id, text)
        return False
    
    async def cleanup(self):
        """清理所有Bot实例"""
        for bot in self.bots.values():
            if bot.session:
                await bot.session.close()
        self.bots.clear()
        self.bot_configs.clear()


# 全局Bot管理器实例
telegram_bot_manager = TelegramBotManager()
