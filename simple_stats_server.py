#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的用户统计服务器
只统计有多少人在使用闲鱼自动回复系统
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import sqlite3
from datetime import datetime
import uvicorn
from pathlib import Path

app = FastAPI(title="闲鱼自动回复系统用户统计", version="1.0.0")

# 数据库文件路径
DB_PATH = Path(__file__).parent / "user_stats.db"


class UserStats(BaseModel):
    """用户统计数据模型"""
    anonymous_id: str
    timestamp: str
    project: str
    info: Dict[str, Any]


def init_database():
    """初始化统计数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 创建用户统计表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anonymous_id TEXT UNIQUE NOT NULL,
        project TEXT NOT NULL,
        os_type TEXT,
        version TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        visit_count INTEGER DEFAULT 1
    )
    ''')
    
    conn.commit()
    conn.close()


def save_user_stats(data: UserStats) -> bool:
    """保存用户统计数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 提取信息
        os_type = data.info.get('os', 'Unknown')
        version = data.info.get('version', 'Unknown')
        
        # 检查用户是否已存在
        cursor.execute('''
        SELECT id, visit_count FROM user_statistics 
        WHERE anonymous_id = ? AND project = ?
        ''', (data.anonymous_id, data.project))
        
        existing = cursor.fetchone()
        
        if existing:
            # 更新现有用户
            cursor.execute('''
            UPDATE user_statistics 
            SET last_seen = CURRENT_TIMESTAMP, 
                visit_count = visit_count + 1,
                os_type = ?,
                version = ?
            WHERE anonymous_id = ? AND project = ?
            ''', (os_type, version, data.anonymous_id, data.project))
            print(f"更新用户统计: {data.anonymous_id} (访问次数: {existing[1] + 1})")
        else:
            # 插入新用户
            cursor.execute('''
            INSERT INTO user_statistics 
            (anonymous_id, project, os_type, version, first_seen, last_seen, visit_count)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
            ''', (data.anonymous_id, data.project, os_type, version))
            print(f"新增用户统计: {data.anonymous_id}")
        
        conn.commit()
        return True
        
    except Exception as e:
        print(f"保存用户统计失败: {e}")
        return False
    finally:
        conn.close()


@app.post('/statistics')
async def receive_user_stats(data: UserStats):
    """接收用户统计数据"""
    try:
        success = save_user_stats(data)
        
        if success:
            print(f"收到用户统计: {data.anonymous_id}")
            return {"status": "success", "message": "用户统计已收到"}
        else:
            return {"status": "error", "message": "保存统计数据失败"}
            
    except Exception as e:
        print(f"处理用户统计失败: {e}")
        return {"status": "error", "message": "处理统计数据失败"}


@app.get('/stats')
async def get_user_stats():
    """获取用户统计摘要"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 总用户数
        cursor.execute('SELECT COUNT(*) FROM user_statistics')
        total_users = cursor.fetchone()[0]
        
        # 按操作系统分组
        cursor.execute('''
        SELECT os_type, COUNT(*) as count 
        FROM user_statistics 
        GROUP BY os_type 
        ORDER BY count DESC
        ''')
        os_stats = dict(cursor.fetchall())
        
        # 按版本分组
        cursor.execute('''
        SELECT version, COUNT(*) as count 
        FROM user_statistics 
        GROUP BY version 
        ORDER BY count DESC
        ''')
        version_stats = dict(cursor.fetchall())
        
        # 最近活跃用户（7天内）
        cursor.execute('''
        SELECT COUNT(*) FROM user_statistics 
        WHERE last_seen >= datetime('now', '-7 days')
        ''')
        recent_active = cursor.fetchone()[0]
        
        return {
            "total_users": total_users,
            "recent_active_users": recent_active,
            "os_distribution": os_stats,
            "version_distribution": version_stats,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"获取统计数据失败: {e}")
        return {"error": "获取统计数据失败"}
    finally:
        conn.close()


@app.get('/stats/recent')
async def get_recent_users():
    """获取最近活跃用户"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        SELECT anonymous_id, os_type, version, last_seen, visit_count
        FROM user_statistics 
        WHERE last_seen >= datetime('now', '-7 days')
        ORDER BY last_seen DESC
        LIMIT 50
        ''')
        
        users = []
        for row in cursor.fetchall():
            users.append({
                "anonymous_id": row[0],
                "os_type": row[1],
                "version": row[2],
                "last_seen": row[3],
                "visit_count": row[4]
            })
        
        return {
            "recent_users": users,
            "count": len(users)
        }
        
    except Exception as e:
        print(f"获取最近用户失败: {e}")
        return {"error": "获取最近用户失败"}
    finally:
        conn.close()


@app.get('/')
async def root():
    """根路径"""
    return {
        "message": "闲鱼自动回复系统用户统计服务器",
        "description": "只统计有多少人在使用这个系统",
        "endpoints": {
            "POST /statistics": "接收用户统计数据",
            "GET /stats": "获取用户统计摘要",
            "GET /stats/recent": "获取最近活跃用户"
        }
    }


if __name__ == "__main__":
    # 初始化数据库
    init_database()
    print("用户统计数据库初始化完成")
    
    # 启动服务器
    print("启动用户统计服务器...")
    print("访问 http://localhost:8081/stats 查看统计信息")
    uvicorn.run(app, host="0.0.0.0", port=8081)
