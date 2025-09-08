import re
import time
import asyncio
from typing import Dict, List, Optional, Any
from loguru import logger
from db_manager import db_manager


class TelegramCommandHandler:
    """Telegram命令处理器，处理用户发送的文本命令"""
    
    def __init__(self):
        """初始化命令处理器"""
        self.db_manager = db_manager
        
        # 定义命令模式和对应的处理方法
        self.command_patterns = {
            r'^回复\s+#(\w+)\s+(.+)$': self.handle_reply_command,
            r'^AI\s+#(\w+)$': self.handle_ai_command,
            r'^忽略\s+#(\w+)$': self.handle_ignore_command,
            r'^查看\s+#(\w+)$': self.handle_view_command,
            r'^列表$': self.handle_list_command,
            r'^状态$': self.handle_status_command,
            r'^帮助$': self.handle_help_command,
            r'^确认\s+#(\w+)$': self.handle_confirm_command,
            r'^模板\s+#(\w+)\s+(.+)$': self.handle_template_command,
            r'^模板列表$': self.handle_template_list_command,
            r'^批量忽略\s+(.+)$': self.handle_batch_ignore_command,
            r'^搜索\s+(.+)$': self.handle_search_command,
            r'^统计$': self.handle_stats_command,
            r'^统计\s+(\d+)$': self.handle_stats_command,
        }
        
        # 消息处理锁，防止重复操作
        self.processing_locks = {}
        
        logger.info("Telegram命令处理器初始化完成")
    
    async def process_command(self, telegram_message: str, telegram_chat_id: int) -> str:
        """处理Telegram命令"""
        try:
            message = telegram_message.strip()
            logger.info(f"处理Telegram命令: {message} (Chat ID: {telegram_chat_id})")
            
            # 遍历命令模式，找到匹配的处理方法
            for pattern, handler in self.command_patterns.items():
                match = re.match(pattern, message, re.IGNORECASE)
                if match:
                    logger.debug(f"命令匹配成功: {pattern}")
                    return await handler(match, telegram_chat_id)
            
            # 没有匹配的命令
            return self._get_help_message()
            
        except Exception as e:
            logger.error(f"处理Telegram命令异常: {e}")
            return f"❌ 命令处理失败: {str(e)}"

    async def process_reply_message(self, reply_to_message: dict, reply_text: str, telegram_chat_id: int) -> str:
        """处理Telegram回复消息"""
        try:
            logger.info(f"处理Telegram回复消息: {reply_text}")

            # 从被回复的消息中查找匹配的消息记录
            original_text = reply_to_message.get('text', '')
            original_message = self._find_message_by_content(original_text, telegram_chat_id)

            if not original_message:
                return "❌ 无法识别要回复的消息，请确保回复的是机器人发送的消息通知"

            message_id = original_message['message_id']
            logger.info(f"通过内容匹配识别到消息ID: {message_id}")

            # 检查消息处理锁
            if message_id in self.processing_locks:
                return "⏳ 消息正在处理中，请稍候..."

            # 设置处理锁
            self.processing_locks[message_id] = True

            try:
                # 验证用户权限
                if original_message['telegram_chat_id'] != telegram_chat_id:
                    return f"❌ 无权限操作此消息"

                # 检查消息状态
                if original_message['status'] == 'replied':
                    return f"❌ 消息 #{message_id} 已经回复过了"

                # 发送回复到闲鱼
                success = await self._send_to_xianyu(original_message, reply_text)
                if not success:
                    return f"❌ 发送失败，请检查账号连接状态"

                # 更新消息状态
                self.db_manager.update_telegram_message_status(
                    message_id, 'replied', reply_text, 'telegram_reply'
                )

                return f"✅ 已回复消息 #{message_id}\n回复内容: {reply_text}"

            finally:
                # 释放处理锁
                if message_id in self.processing_locks:
                    del self.processing_locks[message_id]

        except Exception as e:
            logger.error(f"处理Telegram回复消息异常: {e}")
            return f"❌ 回复失败: {str(e)}"

    def _extract_message_id_from_text(self, text: str) -> Optional[str]:
        """从文本中提取消息ID"""
        try:
            import re
            # 匹配消息ID格式，适应新的消息格式
            patterns = [
                r'消息编号[：:]\s*([A-Z0-9_\u4e00-\u9fff]+)',  # 消息编号: A001_123456_001
                r'消息\s+([A-Z0-9_\u4e00-\u9fff]+)',         # 消息 A001_123456_001
                r'#([A-Z0-9_\u4e00-\u9fff]+)',              # #A001_123456_001
                r'Message\s+([A-Z0-9_\u4e00-\u9fff]+)',     # Message A001_123456_001
                r'([A-Z0-9\u4e00-\u9fff]+_\d+_\d+)',        # 直接匹配格式：外太空的_315509_895
            ]

            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    message_id = match.group(1)
                    logger.debug(f"从文本中提取到消息ID: {message_id}")
                    return message_id

            logger.debug(f"无法从文本中提取消息ID: {text}")
            return None

        except Exception as e:
            logger.error(f"提取消息ID失败: {e}")
            return None

    def _find_message_by_content(self, original_text: str, telegram_chat_id: int) -> Optional[Dict[str, Any]]:
        """通过消息内容查找匹配的消息记录"""
        try:
            # 获取该聊天的所有待处理消息
            messages = self.db_manager.get_telegram_messages_by_chat(telegram_chat_id, 'pending', 50)

            if not messages:
                logger.debug("没有找到待处理的消息")
                return None

            # 尝试通过消息内容匹配
            for message in messages:
                try:
                    # 获取存储的原始消息内容
                    context_data = message.get('context_data')
                    if context_data:
                        import json
                        context = json.loads(context_data)
                        stored_message = context.get('original_message', '')

                        # 比较消息内容的关键部分
                        if self._messages_match(original_text, stored_message):
                            logger.info(f"通过内容匹配找到消息: {message['message_id']}")
                            return message
                except Exception as e:
                    logger.debug(f"处理消息匹配时出错: {e}")
                    continue

            logger.debug("未找到匹配的消息")
            return None

        except Exception as e:
            logger.error(f"查找消息失败: {e}")
            return None

    def _messages_match(self, telegram_text: str, stored_text: str) -> bool:
        """判断两个消息是否匹配"""
        try:
            # 提取关键信息进行匹配
            def extract_key_info(text: str) -> dict:
                import re
                info = {}

                # 提取账号
                account_match = re.search(r'账号[：:]\s*([^\n]+)', text)
                if account_match:
                    info['account'] = account_match.group(1).strip()

                # 提取买家
                buyer_match = re.search(r'买家[：:]\s*([^\n（]+)', text)
                if buyer_match:
                    info['buyer'] = buyer_match.group(1).strip()

                # 提取消息内容
                content_match = re.search(r'消息内容[：:]\s*([^\n]+)', text)
                if content_match:
                    info['content'] = content_match.group(1).strip()

                # 提取聊天ID
                chat_match = re.search(r'聊天ID[：:]\s*([^\n]+)', text)
                if chat_match:
                    info['chat_id'] = chat_match.group(1).strip()

                return info

            telegram_info = extract_key_info(telegram_text)
            stored_info = extract_key_info(stored_text)

            # 至少需要匹配账号和消息内容
            if (telegram_info.get('account') == stored_info.get('account') and
                telegram_info.get('content') == stored_info.get('content')):
                return True

            # 或者匹配买家和聊天ID
            if (telegram_info.get('buyer') == stored_info.get('buyer') and
                telegram_info.get('chat_id') == stored_info.get('chat_id')):
                return True

            return False

        except Exception as e:
            logger.debug(f"消息匹配判断失败: {e}")
            return False
    
    async def handle_reply_command(self, match, telegram_chat_id: int) -> str:
        """处理回复命令: 回复 #消息编号 内容"""
        try:
            message_id = match.group(1)
            reply_content = match.group(2)
            
            logger.info(f"处理回复命令: {message_id} -> {reply_content}")
            
            # 检查消息处理锁
            if message_id in self.processing_locks:
                return "⏳ 消息正在处理中，请稍候..."
            
            # 设置处理锁
            self.processing_locks[message_id] = True
            
            try:
                # 查找原始消息
                original_message = self.db_manager.get_telegram_message_by_id(message_id)
                if not original_message:
                    return f"❌ 消息 #{message_id} 不存在或已过期"
                
                # 验证用户权限
                if original_message['telegram_chat_id'] != telegram_chat_id:
                    return f"❌ 无权限操作消息 #{message_id}"
                
                # 检查消息状态
                if original_message['status'] == 'replied':
                    return f"❌ 消息 #{message_id} 已经回复过了"
                
                # 发送回复到闲鱼
                success = await self._send_to_xianyu(original_message, reply_content)
                if not success:
                    return f"❌ 发送失败，请检查账号连接状态"
                
                # 更新消息状态
                self.db_manager.update_telegram_message_status(
                    message_id, 'replied', reply_content, 'manual'
                )
                
                return f"✅ 已回复消息 #{message_id}\n回复内容: {reply_content}"
                
            finally:
                # 释放处理锁
                if message_id in self.processing_locks:
                    del self.processing_locks[message_id]
                    
        except Exception as e:
            logger.error(f"处理回复命令异常: {e}")
            return f"❌ 回复失败: {str(e)}"
    
    async def handle_ai_command(self, match, telegram_chat_id: int) -> str:
        """处理AI回复命令: AI #消息编号"""
        try:
            message_id = match.group(1)
            logger.info(f"处理AI回复命令: {message_id}")

            # 检查消息处理锁
            if message_id in self.processing_locks:
                return "⏳ 消息正在处理中，请稍候..."

            # 设置处理锁
            self.processing_locks[message_id] = True

            try:
                # 查找原始消息
                original_message = self.db_manager.get_telegram_message_by_id(message_id)
                if not original_message:
                    return f"❌ 消息 #{message_id} 不存在"

                # 验证用户权限
                if original_message['telegram_chat_id'] != telegram_chat_id:
                    return f"❌ 无权限操作消息 #{message_id}"

                # 检查消息状态
                if original_message['status'] == 'replied':
                    return f"❌ 消息 #{message_id} 已经回复过了"

                # 集成AI回复功能
                ai_reply = await self._generate_ai_reply(original_message)
                if not ai_reply:
                    return f"❌ AI回复生成失败，请检查AI配置或稍后重试"

                # 返回AI建议，等待用户确认
                return f"""🤖 **AI回复建议 #{message_id}**

📝 **原始消息**: {original_message['send_message']}
👤 **买家**: {original_message['send_user_name']}

🎯 **AI建议回复**:
{ai_reply}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 **操作选项**:
• `确认 #{message_id}` - 发送AI建议回复
• `回复 #{message_id} [自定义内容]` - 发送自定义回复
• `忽略 #{message_id}` - 忽略此消息
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

            finally:
                # 释放处理锁
                if message_id in self.processing_locks:
                    del self.processing_locks[message_id]

        except Exception as e:
            logger.error(f"处理AI回复命令异常: {e}")
            return f"❌ AI回复失败: {str(e)}"
    
    async def handle_ignore_command(self, match, telegram_chat_id: int) -> str:
        """处理忽略命令: 忽略 #消息编号"""
        try:
            message_id = match.group(1)
            logger.info(f"处理忽略命令: {message_id}")
            
            # 查找原始消息
            original_message = self.db_manager.get_telegram_message_by_id(message_id)
            if not original_message:
                return f"❌ 消息 #{message_id} 不存在"
            
            # 验证用户权限
            if original_message['telegram_chat_id'] != telegram_chat_id:
                return f"❌ 无权限操作消息 #{message_id}"
            
            # 更新消息状态为忽略
            self.db_manager.update_telegram_message_status(
                message_id, 'ignored', None, 'manual'
            )
            
            return f"✅ 已忽略消息 #{message_id}"
            
        except Exception as e:
            logger.error(f"处理忽略命令异常: {e}")
            return f"❌ 忽略失败: {str(e)}"
    
    async def handle_view_command(self, match, telegram_chat_id: int) -> str:
        """处理查看命令: 查看 #消息编号"""
        try:
            message_id = match.group(1)
            logger.info(f"处理查看命令: {message_id}")
            
            # 查找原始消息
            original_message = self.db_manager.get_telegram_message_by_id(message_id)
            if not original_message:
                return f"❌ 消息 #{message_id} 不存在"
            
            # 验证用户权限
            if original_message['telegram_chat_id'] != telegram_chat_id:
                return f"❌ 无权限查看消息 #{message_id}"
            
            # 格式化消息详情
            status_text = {
                'pending': '⏳ 待处理',
                'replied': '✅ 已回复',
                'ignored': '🚫 已忽略'
            }.get(original_message['status'], original_message['status'])
            
            detail_text = f"""
📋 **消息详情 #{message_id}**

👤 **买家**: {original_message['send_user_name']} ({original_message['send_user_id']})
🏪 **账号**: {original_message['cookie_id']}
💬 **内容**: {original_message['send_message']}
📍 **对话ID**: {original_message['chat_id']}
📊 **状态**: {status_text}
🕒 **创建时间**: {original_message['created_at']}
"""
            
            if original_message['replied_at']:
                detail_text += f"✅ **回复时间**: {original_message['replied_at']}\n"
            
            if original_message['reply_content']:
                detail_text += f"💬 **回复内容**: {original_message['reply_content']}\n"
            
            return detail_text.strip()
            
        except Exception as e:
            logger.error(f"处理查看命令异常: {e}")
            return f"❌ 查看失败: {str(e)}"
    
    async def handle_list_command(self, match, telegram_chat_id: int) -> str:
        """处理列表命令: 列表"""
        try:
            logger.info(f"处理列表命令 (Chat ID: {telegram_chat_id})")
            
            # 获取待处理消息列表
            pending_messages = self.db_manager.get_telegram_messages_by_chat(
                telegram_chat_id, status='pending', limit=10
            )
            
            if not pending_messages:
                return "📭 暂无待处理消息"
            
            result = f"📋 **待处理消息** ({len(pending_messages)} 条):\n\n"
            
            for msg in pending_messages:
                time_ago = self._get_time_ago(msg['created_at'])
                result += f"#{msg['message_id']} ({time_ago})\n"
                result += f"👤 {msg['send_user_name']}: {msg['send_message'][:50]}...\n"
                result += f"🏪 {msg['cookie_id']}\n\n"
            
            result += "💡 使用 '回复 #消息编号 内容' 进行回复"
            return result
            
        except Exception as e:
            logger.error(f"处理列表命令异常: {e}")
            return f"❌ 获取列表失败: {str(e)}"
    
    async def handle_status_command(self, match, telegram_chat_id: int) -> str:
        """处理状态命令: 状态"""
        try:
            logger.info(f"处理状态命令 (Chat ID: {telegram_chat_id})")
            
            # 获取各状态的消息数量
            all_messages = self.db_manager.get_telegram_messages_by_chat(
                telegram_chat_id, limit=1000
            )
            
            pending_count = len([m for m in all_messages if m['status'] == 'pending'])
            replied_count = len([m for m in all_messages if m['status'] == 'replied'])
            ignored_count = len([m for m in all_messages if m['status'] == 'ignored'])
            
            status_text = f"""
📊 **消息状态统计**

⏳ **待处理**: {pending_count} 条
✅ **已回复**: {replied_count} 条
🚫 **已忽略**: {ignored_count} 条
📈 **总计**: {len(all_messages)} 条

💡 使用 '列表' 查看待处理消息
"""
            return status_text.strip()
            
        except Exception as e:
            logger.error(f"处理状态命令异常: {e}")
            return f"❌ 获取状态失败: {str(e)}"
    
    async def handle_help_command(self, match, telegram_chat_id: int) -> str:
        """处理帮助命令: 帮助"""
        return self._get_help_message()
    
    async def handle_confirm_command(self, match, telegram_chat_id: int) -> str:
        """处理确认命令: 确认 #消息编号"""
        try:
            message_id = match.group(1)
            logger.info(f"处理确认命令: {message_id}")

            # 检查消息处理锁
            if message_id in self.processing_locks:
                return "⏳ 消息正在处理中，请稍候..."

            # 设置处理锁
            self.processing_locks[message_id] = True

            try:
                # 查找原始消息
                original_message = self.db_manager.get_telegram_message_by_id(message_id)
                if not original_message:
                    return f"❌ 消息 #{message_id} 不存在"

                # 验证用户权限
                if original_message['telegram_chat_id'] != telegram_chat_id:
                    return f"❌ 无权限操作消息 #{message_id}"

                # 检查消息状态
                if original_message['status'] == 'replied':
                    return f"❌ 消息 #{message_id} 已经回复过了"

                # 生成AI回复
                ai_reply = await self._generate_ai_reply(original_message)
                if not ai_reply:
                    return f"❌ AI回复生成失败，请检查AI配置"

                # 发送AI回复到闲鱼
                success = await self._send_to_xianyu(original_message, ai_reply)
                if not success:
                    return f"❌ 发送失败，请检查账号连接状态"

                # 更新消息状态
                self.db_manager.update_telegram_message_status(
                    message_id, 'replied', ai_reply, 'ai'
                )

                return f"✅ 已发送AI回复到消息 #{message_id}\n回复内容: {ai_reply}"

            finally:
                # 释放处理锁
                if message_id in self.processing_locks:
                    del self.processing_locks[message_id]

        except Exception as e:
            logger.error(f"处理确认命令异常: {e}")
            return f"❌ 确认失败: {str(e)}"
    
    def _get_help_message(self) -> str:
        """获取帮助信息"""
        return """
🤖 **Telegram Bot 命令帮助**

**基础回复命令**:
• `回复 #消息编号 内容` - 直接回复闲鱼消息
• `AI #消息编号` - 生成AI智能回复建议
• `确认 #消息编号` - 确认发送AI建议回复
• `模板 #消息编号 模板名称` - 使用模板回复
• `忽略 #消息编号` - 忽略指定消息

**查看管理命令**:
• `查看 #消息编号` - 查看消息详情
• `列表` - 查看待处理消息列表
• `状态` - 查看消息统计信息
• `模板列表` - 查看可用回复模板

**高级功能命令**:
• `批量忽略 #消息1,#消息2` - 批量忽略多条消息
• `搜索 关键词` - 搜索包含关键词的消息
• `统计` - 查看7天消息统计信息
• `统计 天数` - 查看指定天数统计信息
• `帮助` - 显示此帮助信息

**使用示例**:
```
回复 #A001_123456_001 您好，商品还在的
AI #A001_123456_001
确认 #A001_123456_001
模板 #A001_123456_001 问候语
批量忽略 #A001_123456_001,#A001_123456_002
搜索 价格
```

💡 **使用流程**:
1. 收到消息通知后，使用 `AI #消息编号` 获取AI建议
2. 满意AI建议则使用 `确认 #消息编号` 发送
3. 不满意则使用 `回复 #消息编号 自定义内容` 或 `模板 #消息编号 模板名`
4. 不需要回复则使用 `忽略 #消息编号`
"""
    
    def _get_time_ago(self, timestamp_str: str) -> str:
        """计算时间差"""
        try:
            import datetime
            created_time = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            now = datetime.datetime.now(created_time.tzinfo)
            diff = now - created_time
            
            if diff.days > 0:
                return f"{diff.days}天前"
            elif diff.seconds > 3600:
                return f"{diff.seconds // 3600}小时前"
            elif diff.seconds > 60:
                return f"{diff.seconds // 60}分钟前"
            else:
                return "刚刚"
        except:
            return "未知时间"
    
    async def _send_to_xianyu(self, original_message: Dict[str, Any], reply_content: str) -> bool:
        """发送回复到闲鱼"""
        try:
            cookie_id = original_message['cookie_id']
            send_user_id = original_message['send_user_id']

            logger.info(f"准备发送回复到闲鱼: {cookie_id} -> {send_user_id}")

            # 解析context_data获取item_id
            item_id = None
            try:
                import json
                context_data = original_message.get('context_data')
                if context_data:
                    context = json.loads(context_data)
                    # 这里可以从context中获取item_id，如果有的话
                    item_id = context.get('item_id')
            except:
                pass

            # 如果没有item_id，使用默认值
            if not item_id:
                item_id = "unknown"

            # 获取XianyuAutoAsync实例并发送消息
            try:
                # 导入cookie_manager来获取实例
                import cookie_manager

                if cookie_manager.manager and hasattr(cookie_manager.manager, 'instances'):
                    if cookie_id in cookie_manager.manager.instances:
                        instance = cookie_manager.manager.instances[cookie_id]

                        # 使用send_msg_once方法发送消息
                        await instance.send_msg_once(
                            toid=send_user_id,
                            item_id=item_id,
                            text=reply_content
                        )

                        logger.info(f"消息发送成功: {cookie_id} -> {send_user_id}")
                        return True
                    else:
                        logger.warning(f"账号实例不存在: {cookie_id}")
                        return False
                else:
                    logger.warning("CookieManager未初始化或无实例")
                    return False

            except ImportError:
                logger.error("无法导入cookie_manager")
                return False
            except Exception as e:
                logger.error(f"发送消息到闲鱼异常: {e}")
                return False

        except Exception as e:
            logger.error(f"发送回复到闲鱼失败: {e}")
            return False

    async def _generate_ai_reply(self, original_message: Dict[str, Any]) -> Optional[str]:
        """生成AI回复"""
        try:
            cookie_id = original_message['cookie_id']
            send_user_name = original_message['send_user_name']
            send_user_id = original_message['send_user_id']
            send_message = original_message['send_message']
            chat_id = original_message['chat_id']

            # 解析context_data获取item_id
            item_id = "unknown"
            try:
                import json
                context_data = original_message.get('context_data')
                if context_data:
                    context = json.loads(context_data)
                    item_id = context.get('item_id', 'unknown')
            except:
                pass

            # 导入AI回复引擎
            try:
                from ai_reply_engine import ai_reply_engine

                # 检查是否启用AI回复
                if not ai_reply_engine.is_ai_enabled(cookie_id):
                    logger.warning(f"账号 {cookie_id} 未启用AI回复")
                    return None

                # 从数据库获取商品信息
                item_info_raw = self.db_manager.get_item_info(cookie_id, item_id)

                if not item_info_raw:
                    logger.debug(f"数据库中无商品信息: {item_id}")
                    # 使用默认商品信息
                    item_info = {
                        'title': '商品信息获取失败',
                        'price': 0,
                        'desc': '暂无商品描述'
                    }
                else:
                    # 解析数据库中的商品信息
                    item_info = {
                        'title': item_info_raw.get('item_title', '未知商品'),
                        'price': self._parse_price(item_info_raw.get('item_price', '0')),
                        'desc': item_info_raw.get('item_description', '暂无商品描述')
                    }

                # 生成AI回复
                reply = ai_reply_engine.generate_reply(
                    message=send_message,
                    item_info=item_info,
                    chat_id=chat_id,
                    cookie_id=cookie_id,
                    user_id=send_user_id,
                    item_id=item_id
                )

                if reply:
                    logger.info(f"AI回复生成成功: {cookie_id} -> {reply}")
                    return reply
                else:
                    logger.warning(f"AI回复生成失败: {cookie_id}")
                    return None

            except ImportError:
                logger.error("无法导入ai_reply_engine")
                return None
            except Exception as e:
                logger.error(f"AI回复生成异常: {e}")
                return None

        except Exception as e:
            logger.error(f"生成AI回复失败: {e}")
            return None

    def _parse_price(self, price_str: str) -> float:
        """解析价格字符串为数字"""
        try:
            if not price_str:
                return 0.0
            # 移除非数字字符，保留小数点
            import re
            price_clean = re.sub(r'[^\d.]', '', str(price_str))
            return float(price_clean) if price_clean else 0.0
        except:
            return 0.0

    async def handle_template_command(self, match, telegram_chat_id: int) -> str:
        """处理模板回复命令: 模板 #消息编号 模板名称"""
        try:
            message_id = match.group(1)
            template_name = match.group(2)
            logger.info(f"处理模板回复命令: {message_id} -> {template_name}")

            # 查找原始消息
            original_message = self.db_manager.get_telegram_message_by_id(message_id)
            if not original_message:
                return f"❌ 消息 #{message_id} 不存在"

            # 验证用户权限
            if original_message['telegram_chat_id'] != telegram_chat_id:
                return f"❌ 无权限操作消息 #{message_id}"

            # 获取模板回复
            template_reply = await self._get_template_reply(original_message, template_name)
            if not template_reply:
                return f"❌ 模板 '{template_name}' 不存在或获取失败"

            # 发送模板回复到闲鱼
            success = await self._send_to_xianyu(original_message, template_reply)
            if not success:
                return f"❌ 发送失败，请检查账号连接状态"

            # 更新消息状态
            self.db_manager.update_telegram_message_status(
                message_id, 'replied', template_reply, 'template'
            )

            return f"✅ 已使用模板 '{template_name}' 回复消息 #{message_id}\n回复内容: {template_reply}"

        except Exception as e:
            logger.error(f"处理模板回复命令异常: {e}")
            return f"❌ 模板回复失败: {str(e)}"

    async def handle_template_list_command(self, match, telegram_chat_id: int) -> str:
        """处理模板列表命令: 模板列表"""
        try:
            # 获取用户的账号列表
            user_accounts = await self._get_user_accounts_by_chat_id(telegram_chat_id)
            if not user_accounts:
                return "❌ 未找到关联的账号"

            # 获取第一个账号的模板（假设用户主要使用第一个账号）
            cookie_id = user_accounts[0]
            templates = self.db_manager.get_keywords_by_cookie(cookie_id)

            if not templates:
                return f"📝 账号 {cookie_id} 暂无可用模板"

            result = f"📝 **可用模板列表** (账号: {cookie_id}):\n\n"

            for i, template in enumerate(templates[:10], 1):  # 限制显示前10个
                keyword = template.get('keyword', '未知')
                reply_content = template.get('reply_content', '无内容')
                # 截断过长的回复内容
                if len(reply_content) > 30:
                    reply_content = reply_content[:30] + "..."

                result += f"{i}. **{keyword}**\n   {reply_content}\n\n"

            if len(templates) > 10:
                result += f"... 还有 {len(templates) - 10} 个模板\n\n"

            result += "💡 使用方法: `模板 #消息编号 模板名称`"
            return result

        except Exception as e:
            logger.error(f"处理模板列表命令异常: {e}")
            return f"❌ 获取模板列表失败: {str(e)}"

    async def handle_batch_ignore_command(self, match, telegram_chat_id: int) -> str:
        """处理批量忽略命令: 批量忽略 #消息编号1,#消息编号2,..."""
        try:
            message_ids_str = match.group(1)
            # 解析消息ID列表
            message_ids = []
            for part in message_ids_str.split(','):
                part = part.strip()
                if part.startswith('#'):
                    message_ids.append(part[1:])
                else:
                    message_ids.append(part)

            if not message_ids:
                return "❌ 请提供有效的消息编号"

            success_count = 0
            failed_count = 0

            for message_id in message_ids:
                try:
                    # 查找原始消息
                    original_message = self.db_manager.get_telegram_message_by_id(message_id)
                    if not original_message:
                        failed_count += 1
                        continue

                    # 验证用户权限
                    if original_message['telegram_chat_id'] != telegram_chat_id:
                        failed_count += 1
                        continue

                    # 更新消息状态为忽略
                    success = self.db_manager.update_telegram_message_status(
                        message_id, 'ignored', None, 'batch'
                    )

                    if success:
                        success_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    logger.error(f"批量忽略消息 {message_id} 失败: {e}")
                    failed_count += 1

            return f"✅ 批量忽略完成\n成功: {success_count} 条\n失败: {failed_count} 条"

        except Exception as e:
            logger.error(f"处理批量忽略命令异常: {e}")
            return f"❌ 批量忽略失败: {str(e)}"

    async def handle_search_command(self, match, telegram_chat_id: int) -> str:
        """处理搜索命令: 搜索 关键词"""
        try:
            keyword = match.group(1).strip()
            logger.info(f"处理搜索命令: {keyword}")

            # 获取用户的所有消息
            all_messages = self.db_manager.get_telegram_messages_by_chat(
                telegram_chat_id, limit=1000
            )

            # 搜索匹配的消息
            matched_messages = []
            for msg in all_messages:
                if (keyword.lower() in msg['send_message'].lower() or
                    keyword.lower() in msg['send_user_name'].lower() or
                    keyword.lower() in msg['message_id'].lower()):
                    matched_messages.append(msg)

            if not matched_messages:
                return f"🔍 未找到包含 '{keyword}' 的消息"

            result = f"🔍 **搜索结果** (关键词: {keyword}):\n\n"

            for i, msg in enumerate(matched_messages[:5], 1):  # 限制显示前5个
                status_emoji = {
                    'pending': '⏳',
                    'replied': '✅',
                    'ignored': '🚫'
                }.get(msg['status'], '❓')

                result += f"{i}. {status_emoji} **#{msg['message_id']}**\n"
                result += f"   👤 {msg['send_user_name']}\n"
                result += f"   💬 {msg['send_message'][:50]}...\n\n"

            if len(matched_messages) > 5:
                result += f"... 还有 {len(matched_messages) - 5} 条匹配结果\n\n"

            result += "💡 使用 '查看 #消息编号' 查看详情"
            return result

        except Exception as e:
            logger.error(f"处理搜索命令异常: {e}")
            return f"❌ 搜索失败: {str(e)}"

    async def _get_template_reply(self, original_message: Dict[str, Any], template_name: str) -> Optional[str]:
        """获取模板回复"""
        try:
            cookie_id = original_message['cookie_id']

            # 从数据库获取关键词模板
            keywords = self.db_manager.get_keywords_by_cookie(cookie_id)

            for keyword_data in keywords:
                if keyword_data.get('keyword', '').lower() == template_name.lower():
                    reply_content = keyword_data.get('reply_content', '')
                    if reply_content:
                        logger.info(f"找到模板回复: {template_name} -> {reply_content}")
                        return reply_content

            logger.warning(f"未找到模板: {template_name}")
            return None

        except Exception as e:
            logger.error(f"获取模板回复失败: {e}")
            return None

    async def _get_user_accounts_by_chat_id(self, telegram_chat_id: int) -> List[str]:
        """根据Telegram Chat ID获取用户的账号列表"""
        try:
            # 从通知渠道配置中查找对应的用户
            channels = self.db_manager.get_notification_channels()

            for channel in channels:
                if channel['type'] == 'telegram':
                    try:
                        import json
                        config = json.loads(channel['config'])
                        if int(config.get('chat_id', 0)) == telegram_chat_id:
                            user_id = channel['user_id']
                            # 获取该用户的所有账号
                            user_cookies = self.db_manager.get_all_cookies(user_id)
                            return list(user_cookies.keys()) if user_cookies else []
                    except:
                        continue

            return []

        except Exception as e:
            logger.error(f"获取用户账号列表失败: {e}")
            return []

    async def handle_stats_command(self, match, telegram_chat_id: int) -> str:
        """处理统计命令: 统计 [天数]"""
        try:
            # 获取天数参数，默认7天
            days = 7
            if match.groups() and match.group(1):
                try:
                    days = int(match.group(1))
                    if days <= 0 or days > 30:
                        return "❌ 天数必须在1-30之间"
                except ValueError:
                    return "❌ 天数格式无效"

            logger.info(f"处理统计命令: {days}天")

            # 获取统计数据
            stats = self.db_manager.get_telegram_message_stats(telegram_chat_id, days)
            top_users = self.db_manager.get_telegram_top_users(telegram_chat_id, days, 5)

            # 格式化统计信息
            result = f"📊 **Telegram消息统计** (最近{days}天)\n\n"

            # 基础统计
            result += f"📈 **总体数据**:\n"
            result += f"• 总消息数: {stats['total_messages']} 条\n"
            result += f"• 待处理: {stats['pending_count']} 条\n"
            result += f"• 已回复: {stats['replied_count']} 条\n"
            result += f"• 已忽略: {stats['ignored_count']} 条\n"
            result += f"• 回复率: {stats['reply_rate']}%\n\n"

            # 回复方式统计
            if stats['replied_count'] > 0:
                result += f"🤖 **回复方式分布**:\n"
                result += f"• AI回复: {stats['ai_replies']} 条\n"
                result += f"• 手动回复: {stats['manual_replies']} 条\n"
                result += f"• 模板回复: {stats['template_replies']} 条\n\n"

            # 响应时间
            if stats['avg_response_minutes'] > 0:
                if stats['avg_response_minutes'] < 60:
                    response_time = f"{stats['avg_response_minutes']:.1f} 分钟"
                else:
                    hours = stats['avg_response_minutes'] / 60
                    response_time = f"{hours:.1f} 小时"
                result += f"⏱️ **平均响应时间**: {response_time}\n\n"

            # 活跃用户
            if top_users:
                result += f"👥 **最活跃用户** (前5名):\n"
                for i, user in enumerate(top_users, 1):
                    result += f"{i}. **{user['user_name']}**\n"
                    result += f"   消息: {user['message_count']} 条, 回复率: {user['reply_rate']}%\n"
                result += "\n"

            # 每日趋势
            if stats['daily_trends']:
                result += f"📅 **每日消息趋势**:\n"
                for trend in stats['daily_trends'][:5]:
                    result += f"• {trend['date']}: {trend['count']} 条\n"

            return result.strip()

        except Exception as e:
            logger.error(f"处理统计命令异常: {e}")
            return f"❌ 获取统计信息失败: {str(e)}"
