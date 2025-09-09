"""
Telegram回调处理器 - 处理内联键盘按钮点击
"""

import json
from typing import Optional
from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes
from telegram_command_handler import TelegramCommandHandler


class TelegramCallbackHandler:
    """Telegram回调处理器"""
    
    def __init__(self):
        """初始化回调处理器"""
        self.command_handler = TelegramCommandHandler()
        # 用户回复状态：{chat_id: {"message_id": "xxx", "timestamp": xxx}}
        self.user_reply_states = {}
        logger.info("Telegram回调处理器初始化完成")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理回调查询"""
        try:
            query = update.callback_query
            await query.answer()  # 确认回调
            
            callback_data = query.data
            chat_id = query.message.chat_id
            message_id = query.message.message_id
            
            logger.info(f"处理回调: {callback_data} (Chat ID: {chat_id})")
            
            # 解析回调数据
            if callback_data.startswith("reply_"):
                await self._handle_reply_callback(query, callback_data)
            elif callback_data.startswith("ai_"):
                await self._handle_ai_callback(query, callback_data)
            elif callback_data.startswith("ignore_"):
                await self._handle_ignore_callback(query, callback_data)
            elif callback_data.startswith("view_"):
                await self._handle_view_callback(query, callback_data)
            elif callback_data == "list":
                await self._handle_list_callback(query)
            elif callback_data == "status":
                await self._handle_status_callback(query)
            elif callback_data == "help":
                await self._handle_help_callback(query)
            else:
                await query.edit_message_text("❌ 未知的操作")
                
        except Exception as e:
            logger.error(f"处理回调异常: {e}")
            try:
                await query.edit_message_text("❌ 处理操作时发生错误")
            except:
                pass
    
    async def _handle_reply_callback(self, query, callback_data: str):
        """处理回复按钮回调 - 进入回复模式"""
        try:
            message_id = callback_data.replace("reply_", "")
            chat_id = query.message.chat_id

            # 检查消息是否已经回复过
            from db_manager import db_manager
            message_info = db_manager.get_telegram_message_by_id(message_id)
            if not message_info:
                await query.edit_message_text(f"❌ 消息 #{message_id} 不存在或已过期")
                return

            if message_info['status'] == 'replied':
                await query.edit_message_text(f"❌ 消息 #{message_id} 已经回复过了")
                return

            # 设置用户状态为"等待回复输入"
            await self._set_user_reply_state(chat_id, message_id)

            # 更新消息为输入提示
            await query.edit_message_text(
                f"📝 请直接输入回复内容：\n\n"
                f"🚫 发送 /cancel 取消回复"
            )

        except Exception as e:
            logger.error(f"处理回复回调异常: {e}")
            await query.edit_message_text("❌ 处理回复操作失败")
    
    async def _handle_ai_callback(self, query, callback_data: str):
        """处理AI回复按钮回调 - 直接发送AI回复"""
        try:
            message_id = callback_data.replace("ai_", "")
            chat_id = query.message.chat_id

            # 检查消息是否已经回复过
            from db_manager import db_manager
            message_info = db_manager.get_telegram_message_by_id(message_id)
            if not message_info:
                await query.edit_message_text(f"❌ 消息 #{message_id} 不存在或已过期")
                return

            if message_info['status'] == 'replied':
                await query.edit_message_text(f"❌ 消息 #{message_id} 已经回复过了")
                return

            # 更新消息显示正在生成
            await query.edit_message_text(f"🤖 正在生成AI回复并发送...")

            # 生成AI回复
            ai_reply = await self.command_handler._generate_ai_reply(message_info)
            if not ai_reply:
                await query.edit_message_text("❌ AI回复生成失败，请检查AI配置")
                return

            # 直接发送AI回复到闲鱼
            success = await self._send_reply_to_xianyu(message_info, ai_reply)

            if success:
                # 更新消息状态为已回复
                db_manager.update_telegram_message_status(message_id, 'replied', ai_reply, 'telegram_ai_button')

                # 获取买家昵称
                buyer_name = message_info.get('send_user_name', '未知用户')
                await query.edit_message_text(f"✅ AI回复已发送给闲鱼用户：{buyer_name}")
            else:
                await query.edit_message_text(f"❌ AI回复发送失败，请检查账号连接状态")

        except Exception as e:
            logger.error(f"处理AI回调异常: {e}")
            await query.edit_message_text("❌ 生成AI回复失败")
    
    async def _handle_ignore_callback(self, query, callback_data: str):
        """处理忽略按钮回调"""
        try:
            message_id = callback_data.replace("ignore_", "")
            
            # 调用忽略处理
            import re
            match = re.match(r'(\w+)', message_id)
            if match:
                response = await self.command_handler.handle_ignore_command(match, query.message.chat_id)
                await query.edit_message_text(response)
            else:
                await query.edit_message_text("❌ 消息ID格式错误")
                
        except Exception as e:
            logger.error(f"处理忽略回调异常: {e}")
            await query.edit_message_text("❌ 忽略操作失败")
    
    async def _handle_view_callback(self, query, callback_data: str):
        """处理查看按钮回调"""
        try:
            message_id = callback_data.replace("view_", "")
            
            # 调用查看处理
            import re
            match = re.match(r'(\w+)', message_id)
            if match:
                response = await self.command_handler.handle_view_command(match, query.message.chat_id)
                await query.edit_message_text(response)
            else:
                await query.edit_message_text("❌ 消息ID格式错误")
                
        except Exception as e:
            logger.error(f"处理查看回调异常: {e}")
            await query.edit_message_text("❌ 查看操作失败")
    
    async def _handle_list_callback(self, query):
        """处理列表按钮回调"""
        try:
            import re
            match = re.match(r'', '')  # 空匹配，用于调用列表命令
            response = await self.command_handler.handle_list_command(match, query.message.chat_id)
            await query.edit_message_text(response)
            
        except Exception as e:
            logger.error(f"处理列表回调异常: {e}")
            await query.edit_message_text("❌ 获取列表失败")
    
    async def _handle_status_callback(self, query):
        """处理状态按钮回调"""
        try:
            import re
            match = re.match(r'', '')  # 空匹配，用于调用状态命令
            response = await self.command_handler.handle_status_command(match, query.message.chat_id)
            await query.edit_message_text(response)
            
        except Exception as e:
            logger.error(f"处理状态回调异常: {e}")
            await query.edit_message_text("❌ 获取状态失败")
    
    async def _handle_help_callback(self, query):
        """处理帮助按钮回调"""
        try:
            import re
            match = re.match(r'', '')  # 空匹配，用于调用帮助命令
            response = await self.command_handler.handle_help_command(match, query.message.chat_id)
            await query.edit_message_text(response)
            
        except Exception as e:
            logger.error(f"处理帮助回调异常: {e}")
            await query.edit_message_text("❌ 获取帮助失败")

    async def _set_user_reply_state(self, chat_id: int, message_id: str):
        """设置用户回复状态"""
        import time
        self.user_reply_states[chat_id] = {
            "message_id": message_id,
            "timestamp": time.time()
        }
        logger.info(f"设置用户 {chat_id} 进入回复模式，消息ID: {message_id}")

    def get_user_reply_state(self, chat_id: int) -> dict:
        """获取用户回复状态"""
        return self.user_reply_states.get(chat_id)

    def clear_user_reply_state(self, chat_id: int):
        """清除用户回复状态"""
        if chat_id in self.user_reply_states:
            del self.user_reply_states[chat_id]
            logger.info(f"清除用户 {chat_id} 的回复状态")

    async def handle_direct_reply(self, chat_id: int, reply_text: str) -> str:
        """处理用户的直接回复"""
        try:
            # 获取回复状态
            reply_state = self.get_user_reply_state(chat_id)
            if not reply_state:
                return "❌ 当前不在回复模式，请先点击消息的回复按钮"

            message_id = reply_state["message_id"]

            # 清除回复状态
            self.clear_user_reply_state(chat_id)

            # 调用实际的回复处理
            from db_manager import db_manager

            # 获取消息详情
            message_info = db_manager.get_telegram_message_by_id(message_id)
            if not message_info:
                return f"❌ 未找到消息 #{message_id}"

            # 发送回复到闲鱼
            success = await self._send_reply_to_xianyu(message_info, reply_text)

            if success:
                # 更新消息状态为已回复
                db_manager.update_telegram_message_status(message_id, 'replied', reply_text, 'telegram_button')

                # 获取买家昵称
                buyer_name = message_info.get('send_user_name', '未知用户')
                return f"✅ 回复已发送给闲鱼用户：{buyer_name}"
            else:
                return f"❌ 发送回复失败\n📋 消息ID: #{message_id}"

        except Exception as e:
            logger.error(f"处理直接回复异常: {e}")
            return f"❌ 处理回复时发生错误: {str(e)}"

    async def _send_reply_to_xianyu(self, message_info: dict, reply_text: str) -> bool:
        """发送回复到闲鱼"""
        try:
            import aiohttp

            cookie_id = message_info.get('cookie_id')
            to_user_id = message_info.get('send_user_id')

            # 获取API密钥
            api_key = self._get_api_key()

            # 通过Telegram专用API发送消息
            api_url = "http://localhost:8080/telegram/send-message"
            payload = {
                "api_key": api_key,
                "cookie_id": cookie_id,
                "chat_id": message_info.get('chat_id', ''),
                "to_user_id": to_user_id,
                "message": reply_text
            }

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, timeout=timeout) as response:
                    result = await response.json()

                    if result.get('success'):
                        logger.info(f"闲鱼回复发送成功: {cookie_id} -> {to_user_id}")
                        return True
                    else:
                        logger.error(f"闲鱼回复发送失败: {result.get('message', '未知错误')}")
                        return False

        except Exception as e:
            logger.error(f"发送闲鱼回复异常: {e}")
            return False

    def _get_api_key(self) -> str:
        """获取Telegram专用API密钥"""
        try:
            from db_manager import db_manager
            # 从系统设置中获取Telegram专用API密钥
            api_key = db_manager.get_system_setting('telegram_reply_secret_key')
            if api_key:
                return api_key

            # 如果没有设置，使用默认值
            return "xianyuvip2025"

        except Exception as e:
            logger.error(f"获取API密钥失败: {e}")
            return "xianyuvip2025"


# 全局回调处理器实例
telegram_callback_handler = TelegramCallbackHandler()
