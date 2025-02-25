# script/MoodDetector/main.py

import logging
import os
import sys
import json
import time
import random
from collections import defaultdict

# 添加项目根目录到sys.path
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.config import *
from app.api import *
from app.switch import load_switch, save_switch
from app.scripts.MoodDetector.LLM import (
    send_dify_request,
    handle_dify_response,
)

# 数据存储路径，实际开发时，请将MoodDetector替换为具体的数据存放路径
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "MoodDetector",
)

# 临时消息id列表
temp_message_ids = []

# 用户消息存储
user_messages = defaultdict(list)  # 存储用户消息
user_activity = defaultdict(int)  # 记录用户活跃度
last_api_call = defaultdict(float)  # 记录上次API调用时间
API_COOLDOWN = 60  # API调用冷却时间（秒）
API_CALL_CHANCE = 0.5  # API调用概率


def get_message_limit(activity):
    """根据活跃度确定消息存储上限"""
    if activity > 50:
        return 10
    elif activity > 20:
        return 7
    else:
        return 5


# 查看功能开关状态
def load_function_status(group_id):
    return load_switch(group_id, "MoodDetector")


# 保存功能开关状态
def save_function_status(group_id, status):
    save_switch(group_id, "MoodDetector", status)


# 处理元事件，用于启动时确保数据目录存在
async def handle_meta_event(websocket, msg):
    """处理元事件"""
    os.makedirs(DATA_DIR, exist_ok=True)


# 处理开关状态
async def toggle_function_status(websocket, group_id, message_id, authorized):
    if not authorized:
        await send_group_msg(
            websocket,
            group_id,
            f"[CQ:reply,id={message_id}]❌❌❌你没有权限对MoodDetector功能进行操作,请联系管理员。",
        )
        return

    if load_function_status(group_id):
        save_function_status(group_id, False)
        await send_group_msg(
            websocket,
            group_id,
            f"[CQ:reply,id={message_id}]🚫🚫🚫MoodDetector功能已关闭",
        )
    else:
        save_function_status(group_id, True)
        await send_group_msg(
            websocket,
            group_id,
            f"[CQ:reply,id={message_id}]✅✅✅MoodDetector功能已开启",
        )


# 群消息处理函数
async def handle_group_message(websocket, msg):
    """处理群消息"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        user_id = str(msg.get("user_id"))
        group_id = str(msg.get("group_id"))
        raw_message = str(msg.get("raw_message"))
        message_id = str(msg.get("message_id"))
        authorized = user_id in owner_id

        # 处理开关命令
        if raw_message == "md":
            await toggle_function_status(websocket, group_id, message_id, authorized)
            return

        # 检查功能是否开启
        if load_function_status(group_id):
            # 更新用户活跃度和消息记录
            user_activity[user_id] += 1
            message_limit = get_message_limit(user_activity[user_id])

            # 存储用户消息
            user_messages[user_id].append(raw_message)
            if len(user_messages[user_id]) > message_limit:
                user_messages[user_id].pop(0)

            # 检查是否需要调用API
            current_time = time.time()
            if (
                len(user_messages[user_id]) >= message_limit
                and current_time - last_api_call[user_id] > API_COOLDOWN
                and random.random() < API_CALL_CHANCE
            ):

                await process_accumulated_messages(websocket, msg, user_id)
                # 清空该用户的消息记录
                user_messages[user_id].clear()
                last_api_call[user_id] = current_time

    except Exception as e:
        logging.error(f"处理MoodDetector群消息失败: {e}")
        await send_group_msg(
            websocket,
            group_id,
            "处理MoodDetector群消息失败，错误信息：" + str(e),
        )
        return


async def process_accumulated_messages(websocket, msg, user_id):
    """处理累积的消息"""
    group_id = str(msg.get("group_id"))
    message_id = str(msg.get("message_id"))

    # 合并用户的历史消息
    combined_message = "\n".join(user_messages[user_id])
    logging.info(f"开始对用户{user_id}的心情进行检测")
    response = await send_dify_request(user_id, combined_message)
    response = json.loads(response)
    answer, total_tokens, total_price, currency = handle_dify_response(response)

    message = [
        {"type": "reply", "data": {"id": message_id}},
        {
            "type": "text",
            "data": {
                "text": f"{answer}\n\n{total_tokens} tokens\n{total_price} {currency}"
            },
        },
    ]
    await send_group_msg(websocket, group_id, message)


# 私聊消息处理函数
async def handle_private_message(websocket, msg):
    """处理私聊消息"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        user_id = str(msg.get("user_id"))
        raw_message = str(msg.get("raw_message"))
        # 私聊消息处理逻辑
        pass
    except Exception as e:
        logging.error(f"处理MoodDetector私聊消息失败: {e}")
        await send_private_msg(
            websocket,
            msg.get("user_id"),
            "处理MoodDetector私聊消息失败，错误信息：" + str(e),
        )
        return


# 群通知处理函数
async def handle_group_notice(websocket, msg):
    """处理群通知"""
    # 确保数据目录存在
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        user_id = str(msg.get("user_id"))
        group_id = str(msg.get("group_id"))
        raw_message = str(msg.get("raw_message"))
        role = str(msg.get("sender", {}).get("role"))
        message_id = str(msg.get("message_id"))

    except Exception as e:
        logging.error(f"处理MoodDetector群通知失败: {e}")
        await send_group_msg(
            websocket,
            group_id,
            "处理MoodDetector群通知失败，错误信息：" + str(e),
        )
        return


# 回应事件处理函数
async def handle_response(websocket, msg):
    """处理回调事件"""
    try:
        echo = msg.get("echo")
        # 处理回调事件
        pass
    except Exception as e:
        logging.error(f"处理MoodDetector回调事件失败: {e}")
        return


# 统一事件处理入口
async def handle_events(websocket, msg):
    """统一事件处理入口"""
    post_type = msg.get("post_type", "response")  # 添加默认值
    try:
        # 处理回调事件
        if msg.get("status") == "ok":
            await handle_response(websocket, msg)
            return

        post_type = msg.get("post_type")

        # 处理元事件
        if post_type == "meta_event":
            await handle_meta_event(websocket, msg)

        # 处理消息事件
        elif post_type == "message":
            message_type = msg.get("message_type")
            if message_type == "group":
                await handle_group_message(websocket, msg)
            elif message_type == "private":
                await handle_private_message(websocket, msg)

        # 处理通知事件
        elif post_type == "notice":
            if msg.get("notice_type") == "group":
                await handle_group_notice(websocket, msg)

    except Exception as e:
        error_type = {
            "message": "消息",
            "notice": "通知",
            "request": "请求",
            "meta_event": "元事件",
        }.get(post_type, "未知")

        logging.error(f"处理MoodDetector{error_type}事件失败: {e}")

        # 发送错误提示
        if post_type == "message":
            message_type = msg.get("message_type")
            if message_type == "group":
                await send_group_msg(
                    websocket,
                    msg.get("group_id"),
                    f"处理MoodDetector{error_type}事件失败，错误信息：{str(e)}",
                )
            elif message_type == "private":
                await send_private_msg(
                    websocket,
                    msg.get("user_id"),
                    f"处理MoodDetector{error_type}事件失败，错误信息：{str(e)}",
                )
