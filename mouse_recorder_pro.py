# -*- coding: utf-8 -*-
"""
================================================================================
鼠小侠 - 轻量化键鼠录制回放工具 (Windows 桌面端)
================================================================================
版本：v3.0
开发语言：Python 3.10+
GUI框架：tkinter（内置轻量化）
底层库：pynput（全局监听）、pyautogui（模拟回放）、json（脚本存储）

架构分层：
    1. 监听层     - 全局鼠标键盘事件监听
    2. 数据存储层 - 脚本加密保存/加载
    3. 回放模拟层 - 键鼠动作模拟回放
    4. UI界面层   - tkinter GUI界面

作者：资深桌面端Python开发工程师
================================================================================
"""

import json
import os
import sys
import time
import threading
import shutil
import base64
import hashlib
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Callable, Dict, Any
from enum import Enum
from datetime import datetime

# 第三方库
import pyautogui
from pynput import mouse, keyboard


# ================================================================================
# 全局配置
# ================================================================================

# pyautogui 安全配置
pyautogui.FAILSAFE = True   # 鼠标移到左上角可紧急停止
pyautogui.PAUSE = 0         # 不在动作间插入额外停顿

# 应用信息
APP_NAME = "鼠小侠"
APP_VERSION = "v3.0"
APP_AUTHOR = "资深桌面端Python开发工程师"

# 加密密钥（用于JSON脚本加密，防止乱码）
ENCRYPT_KEY = "MouseRecorderPro2024"


# ================================================================================
# 枚举与数据类定义
# ================================================================================

class AppState(Enum):
    """应用状态枚举"""
    IDLE = "idle"           # 待机
    RECORDING = "recording" # 录制中
    PLAYING = "playing"     # 回放中


class MouseActionType(Enum):
    """鼠标动作类型枚举"""
    MOVE = "move"               # 普通移动（无按键）
    LEFT_CLICK = "left_click"   # 左键单击
    LEFT_DOUBLE = "left_double" # 左键双击
    RIGHT_CLICK = "right_click" # 右键单击
    LEFT_DRAG = "left_drag"     # 左键拖动（按下左键后移动）
    RIGHT_DRAG = "right_drag"   # 右键拖动（按下右键后移动）
    SCROLL = "scroll"           # 滚轮
    KEYFRAME = "keyframe"       # 关键帧标记（空格键触发）


@dataclass
class MouseAction:
    """
    鼠标动作数据类
    
    属性：
        action_type: 动作类型
        x: 屏幕X坐标
        y: 屏幕Y坐标
        interval: 距离上一个动作的时间间隔（秒）
        scroll_dy: 滚轮垂直滚动量（正数向上，负数向下）
        scroll_dx: 滚轮水平滚动量（正数向右，负数向左）
        timestamp: 动作发生时的绝对时间戳
        is_keyframe: 是否为关键帧
        action_subtype: 动作子类型，用于区分鼠标/键盘动作
        key: 键盘按键（仅键盘动作有效）
        key_char: 键盘按键的字符表示（仅键盘动作有效）
        key_code: 键盘按键的VK码（仅特殊键有效）
    """
    action_type: str
    x: int
    y: int
    interval: float
    scroll_dy: int = 0
    scroll_dx: int = 0
    timestamp: float = 0.0
    is_keyframe: bool = False
    action_subtype: str = "mouse"  # "mouse" 或 "keyboard"
    key: str = ""                  # 键盘按键标识
    key_char: str = ""             # 键盘按键字符
    key_code: int = 0              # 键盘按键VK码
    key_is_press: bool = True      # True=按下, False=释放
    is_hotkey: bool = False        # 是否是快捷键按键（F7/F8/F9/F10/F11/F12/ESC）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MouseAction':
        """从字典创建实例"""
        return cls(
            action_type=data.get("action_type", "move"),
            x=data.get("x", 0),
            y=data.get("y", 0),
            interval=data.get("interval", 0.0),
            scroll_dy=data.get("scroll_dy", data.get("scroll_delta", 0)),
            scroll_dx=data.get("scroll_dx", 0),
            timestamp=data.get("timestamp", 0.0),
            is_keyframe=data.get("is_keyframe", False),
            action_subtype=data.get("action_subtype", "mouse"),
            key=data.get("key", ""),
            key_char=data.get("key_char", ""),
            key_code=data.get("key_code", 0),
            key_is_press=data.get("key_is_press", True),
            is_hotkey=data.get("is_hotkey", False)
        )


# ================================================================================
# 第一层：监听层 - 全局鼠标键盘事件监听
# ================================================================================

class MouseEventListener:
    """
    键鼠事件监听器
    
    功能：
        - 使用pynput监听全局鼠标事件
        - 使用pynput监听全局键盘事件
        - 支持后台静默录制（窗口最小化也能录）
        - 自动识别单击/双击
        - 支持键盘按键按下/释放事件录制
        - 防误触：可设置忽略区域
    """
    
    def __init__(self, 
                 on_action_callback: Callable[[MouseAction], None],
                 on_start_callback: Optional[Callable] = None,
                 on_stop_callback: Optional[Callable] = None):
        """
        初始化监听器
        
        参数：
            on_action_callback: 动作回调函数，每次捕获到动作时调用
            on_start_callback: 开始录制回调
            on_stop_callback: 停止录制回调
        """
        self.on_action = on_action_callback
        self.on_start = on_start_callback
        self.on_stop = on_stop_callback
        
        # 监听器实例
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        
        # 录制状态
        self._is_recording = False
        self._last_time: Optional[float] = None
        self._last_left_click_time: float = 0.0
        self._last_left_click_pos: tuple = (0, 0)
        
        # 按键状态追踪（用于识别拖动）
        self._is_left_pressed = False
        self._is_right_pressed = False
        
        # 滚动事件合并缓冲（解决连续滚动记录不充分的问题）
        self._scroll_buffer_dy = 0
        self._scroll_buffer_dx = 0
        self._last_scroll_time = 0.0
        
        # 防误触：忽略区域（录制开始后的前N毫秒内不记录）
        self._ignore_duration_ms: int = 500  # 忽略前500毫秒
        self._record_start_time: float = 0.0
        
        # 关键帧标记（空格键触发）
        self._keyframe_requested = False
        
        # 记录已按下的按键（用于避免重复事件）
        self._pressed_keys = set()
        
        # 快捷键按键集合（不记录到录制中）
        self._hotkey_keys = {'f9', 'f10', 'f11', 'esc', 'space', 'Key.f9', 'Key.f10', 'Key.f11', 'Key.esc', 'Key.space'}
    
    # -------------------------------------------------------------------------
    # 公共接口
    # -------------------------------------------------------------------------
    
    def start_recording(self, ignore_duration_ms: int = 500):
        """
        开始录制
        
        参数：
            ignore_duration_ms: 忽略前多少毫秒的操作（防误触）
        """
        if self._is_recording:
            return
        
        self._is_recording = True
        self._last_time = None
        self._last_left_click_time = 0.0
        self._ignore_duration_ms = ignore_duration_ms
        self._record_start_time = time.time()
        self._keyframe_requested = False
        # 重置按键状态
        self._is_left_pressed = False
        self._is_right_pressed = False
        # 重置滚动缓冲
        self._scroll_buffer_dy = 0
        self._scroll_buffer_dx = 0
        self._last_scroll_time = 0.0
        # 重置键盘按键集合
        self._pressed_keys = set()
        
        # 启动鼠标监听器
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll
        )
        self._mouse_listener.daemon = True
        self._mouse_listener.start()
        
        # 启动键盘监听器（同时监听按键按下和释放）
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._keyboard_listener.daemon = True
        self._keyboard_listener.start()
        
        if self.on_start:
            self.on_start()
    
    def stop_recording(self):
        """停止录制"""
        if not self._is_recording:
            return
        
        # 停止前刷新滚动缓冲，确保最后一段滚动被记录
        current_x, current_y = mouse.Controller().position
        self._flush_scroll_buffer(int(current_x), int(current_y))
        
        self._is_recording = False
        
        # 停止监听器
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None
        
        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None
        
        if self.on_stop:
            self.on_stop()
    
    def is_recording(self) -> bool:
        """返回是否正在录制"""
        return self._is_recording
    
    def request_keyframe(self):
        """请求标记关键帧（由外部快捷键调用）"""
        self._keyframe_requested = True
    
    # -------------------------------------------------------------------------
    # 内部回调方法
    # -------------------------------------------------------------------------
    
    def _should_ignore(self) -> bool:
        """判断当前是否应该忽略事件（防误触）"""
        elapsed_ms = (time.time() - self._record_start_time) * 1000
        return elapsed_ms < self._ignore_duration_ms
    
    def _create_action(self, action_type: MouseActionType, 
                       x: int, y: int, 
                       scroll_dy: int = 0, scroll_dx: int = 0) -> MouseAction:
        """
        创建鼠标动作对象
        
        参数：
            action_type: 动作类型
            x, y: 坐标
            scroll_dy: 滚轮垂直滚动量
            scroll_dx: 滚轮水平滚动量
        """
        now = time.time()
        
        # 计算时间间隔
        if self._last_time is None:
            interval = 0.0
        else:
            interval = now - self._last_time
        
        self._last_time = now
        
        # 检查是否需要标记关键帧
        is_keyframe = self._keyframe_requested
        self._keyframe_requested = False
        
        return MouseAction(
            action_type=action_type.value,
            x=x,
            y=y,
            interval=round(interval, 4),
            scroll_dy=scroll_dy,
            scroll_dx=scroll_dx,
            timestamp=now,
            is_keyframe=is_keyframe,
            action_subtype="mouse"
        )
    
    def _create_key_action(self, key, is_press: bool) -> Optional[MouseAction]:
        """
        创建键盘动作对象
        
        参数：
            key: pynput的key对象
            is_press: True表示按下，False表示释放
        """
        now = time.time()
        
        # 计算时间间隔
        if self._last_time is None:
            interval = 0.0
        else:
            interval = now - self._last_time
        
        self._last_time = now
        
        # 解析按键信息
        key_identifier = ""
        key_char = ""
        key_code = 0
        
        try:
            if hasattr(key, 'char') and key.char is not None:
                # 普通字符键
                key_char = key.char
                key_identifier = key_char
            elif hasattr(key, 'name'):
                # 特殊键（如Key.space, Key.enter等）
                key_identifier = key.name
                key_char = key.name
            elif hasattr(key, 'vk'):
                key_code = key.vk
                key_identifier = f"vk_{key.vk}"
                key_char = key_identifier
            
            # 获取当前鼠标位置
            current_x, current_y = mouse.Controller().position
            
            return MouseAction(
                action_type="key_press" if is_press else "key_release",
                x=int(current_x),
                y=int(current_y),
                interval=round(interval, 4),
                scroll_dy=0,
                scroll_dx=0,
                timestamp=now,
                is_keyframe=False,
                action_subtype="keyboard",
                key=key_identifier,
                key_char=key_char,
                key_code=key_code,
                key_is_press=is_press,
                is_hotkey=False
            )
        except Exception:
            return None
    
    def _is_hotkey(self, key) -> bool:
        """判断按键是否是快捷键（不应记录到录制中）"""
        try:
            if hasattr(key, 'name'):
                if key.name in ('f7', 'f8', 'f9', 'f10', 'f11', 'f12', 'esc'):
                    return True
            if hasattr(key, 'char') and key.char is not None:
                if key.char.lower() in ('\x1b',):  # ESC字符
                    return True
        except Exception:
            pass
        return False
    
    def _on_move(self, x: int, y: int):
        """鼠标移动回调 - 根据按键状态识别普通移动和拖动"""
        if not self._is_recording:
            return
        if self._should_ignore():
            return
        
        # 根据按键状态确定动作类型
        if self._is_left_pressed:
            # 左键拖动
            action = self._create_action(MouseActionType.LEFT_DRAG, int(x), int(y))
        elif self._is_right_pressed:
            # 右键拖动
            action = self._create_action(MouseActionType.RIGHT_DRAG, int(x), int(y))
        else:
            # 普通移动
            action = self._create_action(MouseActionType.MOVE, int(x), int(y))
        
        self.on_action(action)
    
    def _on_click(self, x: int, y: int, button, pressed: bool):
        """鼠标点击回调 - 追踪按键状态并识别单击/双击"""
        if not self._is_recording:
            return
        if self._should_ignore():
            return
        
        now = time.time()
        
        if button == mouse.Button.left:
            if pressed:
                # 左键按下，记录状态
                self._is_left_pressed = True
                
                # 双击检测：两次左键点击间隔小于350ms且位置接近
                time_diff = now - self._last_left_click_time
                pos_diff = abs(x - self._last_left_click_pos[0]) + abs(y - self._last_left_click_pos[1])
                
                if time_diff < 0.35 and pos_diff < 10:
                    # 双击
                    action = self._create_action(MouseActionType.LEFT_DOUBLE, int(x), int(y))
                    self._last_left_click_time = 0  # 重置，避免三连击误判
                else:
                    # 单击
                    action = self._create_action(MouseActionType.LEFT_CLICK, int(x), int(y))
                    self._last_left_click_time = now
                    self._last_left_click_pos = (x, y)
                
                self.on_action(action)
            else:
                # 左键释放，清除状态
                self._is_left_pressed = False
        
        elif button == mouse.Button.right:
            if pressed:
                # 右键按下，记录状态
                self._is_right_pressed = True
                # 右键单击
                action = self._create_action(MouseActionType.RIGHT_CLICK, int(x), int(y))
                self.on_action(action)
            else:
                # 右键释放，清除状态
                self._is_right_pressed = False
    
    def _on_scroll(self, x: int, y: int, dx: int, dy: int):
        """滚轮滚动回调 - 每个事件独立记录，严格 1:1 对应 pynput 的原始 dx/dy
        
        关键设计：
          - 不做任何事件合并/缓冲，pynput 每次触发 on_scroll 就记录一条动作
          - dx/dy 不做任何倍率转换，直接以 pynput 给出的原始值记录
          - 这样回放端调用 Controller.scroll(scroll_dx, scroll_dy) 
            就能保证滚动距离与录制时完全一致
        """
        if not self._is_recording:
            return
        if self._should_ignore():
            return
        
        # 每个滚动事件立即记录为一条独立的 SCROLL 动作
        # dx, dy 按 pynput 原始值直接保存，不累计、不倍乘
        action = self._create_action(
            MouseActionType.SCROLL,
            int(x), int(y),
            scroll_dy=int(dy),
            scroll_dx=int(dx)
        )
        self.on_action(action)
    
    def _flush_scroll_buffer(self, x: int, y: int):
        """兼容保留：停止录制时无需刷缓冲，因为已改为每个事件直接记录"""
        pass
    
    def _on_key_press(self, key):
        """键盘按键按下回调 - 记录键盘操作"""
        if not self._is_recording:
            return
        if self._should_ignore():
            return
        
        # 跳过快捷键按键
        if self._is_hotkey(key):
            return
        
        # 避免重复记录：同键连续按下不重复记录
        try:
            key_str = str(key)
            if key_str in self._pressed_keys:
                return  # 按键已按下，忽略重复事件
            self._pressed_keys.add(key_str)
        except Exception:
            pass
        
        # 记录按键按下事件
        action = self._create_key_action(key, is_press=True)
        if action is not None:
            self.on_action(action)
    
    def _on_key_release(self, key):
        """键盘按键释放回调 - 记录键盘操作"""
        if not self._is_recording:
            return
        if self._should_ignore():
            return
        
        # 跳过快捷键按键
        if self._is_hotkey(key):
            return
        
        # 从已按下集合中移除
        try:
            key_str = str(key)
            if key_str in self._pressed_keys:
                self._pressed_keys.remove(key_str)
        except Exception:
            pass
        
        # 记录按键释放事件
        action = self._create_key_action(key, is_press=False)
        if action is not None:
            self.on_action(action)


# ================================================================================
# 第二层：数据存储层 - 脚本加密保存/加载
# ================================================================================

class ScriptStorage:
    """
    脚本存储管理器
    
    功能：
        - 将录制数据保存为JSON文件
        - 支持简单加密（Base64 + XOR），防止数据乱码
        - 加载历史脚本
        - 脚本元信息管理
    """
    
    def __init__(self, encrypt_key: str = ENCRYPT_KEY):
        """
        初始化存储管理器
        
        参数：
            encrypt_key: 加密密钥
        """
        self.encrypt_key = encrypt_key
        self._generate_xor_key()
    
    def _generate_xor_key(self):
        """生成XOR加密密钥"""
        # 使用MD5生成固定长度的密钥
        key_hash = hashlib.md5(self.encrypt_key.encode()).digest()
        self._xor_key = key_hash
    
    def _xor_encrypt(self, data: bytes) -> bytes:
        """XOR加密"""
        result = bytearray(len(data))
        key_len = len(self._xor_key)
        for i, byte in enumerate(data):
            result[i] = byte ^ self._xor_key[i % key_len]
        return bytes(result)
    
    def _xor_decrypt(self, data: bytes) -> bytes:
        """XOR解密（与加密相同）"""
        return self._xor_encrypt(data)
    
    def save_script(self, 
                    filepath: str, 
                    actions: List[MouseAction], 
                    metadata: Optional[Dict] = None) -> bool:
        """
        保存脚本到文件
        
        参数：
            filepath: 文件路径
            actions: 动作列表
            metadata: 元信息（可选）
        
        返回：
            是否保存成功
        """
        try:
            # 构建脚本数据结构
            script_data = {
                "meta": {
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "author": APP_AUTHOR,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action_count": len(actions),
                    **(metadata or {})
                },
                "actions": [action.to_dict() for action in actions]
            }
            
            # 序列化为JSON
            json_str = json.dumps(script_data, ensure_ascii=False, indent=2)
            json_bytes = json_str.encode("utf-8")
            
            # 加密
            encrypted = self._xor_encrypt(json_bytes)
            encoded = base64.b64encode(encrypted)
            
            # 写入文件
            with open(filepath, "wb") as f:
                f.write(encoded)
            
            return True
        
        except Exception as e:
            print(f"保存脚本失败: {e}")
            return False
    
    def load_script(self, filepath: str) -> Optional[List[MouseAction]]:
        """
        从文件加载脚本
        
        参数：
            filepath: 文件路径
        
        返回：
            动作列表，失败返回None
        """
        try:
            # 读取文件
            with open(filepath, "rb") as f:
                encoded = f.read()
            
            # 解码和解密
            encrypted = base64.b64decode(encoded)
            json_bytes = self._xor_decrypt(encrypted)
            json_str = json_bytes.decode("utf-8")
            
            # 解析JSON
            script_data = json.loads(json_str)
            
            # 提取动作列表
            actions_data = script_data.get("actions", [])
            actions = [MouseAction.from_dict(data) for data in actions_data]
            
            return actions
        
        except Exception as e:
            print(f"加载脚本失败: {e}")
            return None
    
    def load_script_info(self, filepath: str) -> Optional[Dict]:
        """
        加载脚本元信息（不加载动作数据）
        
        参数：
            filepath: 文件路径
        
        返回：
            元信息字典，失败返回None
        """
        try:
            with open(filepath, "rb") as f:
                encoded = f.read()
            
            encrypted = base64.b64decode(encoded)
            json_bytes = self._xor_decrypt(encrypted)
            json_str = json_bytes.decode("utf-8")
            
            script_data = json.loads(json_str)
            return script_data.get("meta", {})
        
        except Exception:
            return None


# ================================================================================
# 第三层：回放模拟层 - 鼠标动作模拟回放
# ================================================================================

class ActionPlayer:
    """
    动作回放器
    
    功能：
        - 多档位速度调节：0.3x/0.5x/1x/2x/3x
        - 循环回放：单次/无限/指定次数
        - 紧急中断：ESC键立即停止
        - 回放进度回调
        - 屏幕边界检查
    """
    
    def __init__(self,
                 on_progress_callback: Optional[Callable[[int, int, float], None]] = None,
                 on_start_callback: Optional[Callable] = None,
                 on_stop_callback: Optional[Callable] = None,
                 on_error_callback: Optional[Callable[[str], None]] = None,
                 on_loop_start_callback: Optional[Callable[[int, int], None]] = None):
        """
        初始化回放器

        参数：
            on_progress_callback: 进度回调 (当前步数, 总步数, 已耗时)
            on_start_callback: 开始回调
            on_stop_callback: 停止回调
            on_error_callback: 错误回调
            on_loop_start_callback: 循环开始回调 (当前循环次数, 总循环次数)
        """
        self.on_progress = on_progress_callback
        self.on_start = on_start_callback
        self.on_stop = on_stop_callback
        self.on_error = on_error_callback
        self.on_loop_start = on_loop_start_callback
        
        # 回放状态
        self._is_playing = False
        self._stop_requested = False
        self._is_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态为未暂停
        self._play_thread: Optional[threading.Thread] = None
        
        # 屏幕尺寸
        self._screen_width, self._screen_height = pyautogui.size()
        
        # pynput鼠标/键盘控制器（与录制使用相同底层库，保证一致性）
        self._mouse_controller = mouse.Controller()
        self._keyboard_controller = keyboard.Controller()
        
        # 特殊键映射表（用于将pynput的特殊键名称转换为Key枚举）
        self._special_key_map = {
            'space': keyboard.Key.space,
            'enter': keyboard.Key.enter,
            'backspace': keyboard.Key.backspace,
            'tab': keyboard.Key.tab,
            'esc': keyboard.Key.esc,
            'escape': keyboard.Key.esc,
            'shift': keyboard.Key.shift,
            'shift_l': keyboard.Key.shift_l,
            'shift_r': keyboard.Key.shift_r,
            'ctrl': keyboard.Key.ctrl,
            'ctrl_l': keyboard.Key.ctrl_l,
            'ctrl_r': keyboard.Key.ctrl_r,
            'alt': keyboard.Key.alt,
            'alt_l': keyboard.Key.alt_l,
            'alt_r': keyboard.Key.alt_r,
            'cmd': keyboard.Key.cmd,
            'cmd_l': keyboard.Key.cmd_l,
            'cmd_r': keyboard.Key.cmd_r,
            'caps_lock': keyboard.Key.caps_lock,
            'num_lock': keyboard.Key.num_lock,
            'scroll_lock': keyboard.Key.scroll_lock,
            'up': keyboard.Key.up,
            'down': keyboard.Key.down,
            'left': keyboard.Key.left,
            'right': keyboard.Key.right,
            'home': keyboard.Key.home,
            'end': keyboard.Key.end,
            'page_up': keyboard.Key.page_up,
            'page_down': keyboard.Key.page_down,
            'delete': keyboard.Key.delete,
            'insert': keyboard.Key.insert,
            'print_screen': keyboard.Key.print_screen,
            'pause': keyboard.Key.pause,
            'menu': keyboard.Key.menu,
        }
        
        # 添加F1-F12
        for i in range(1, 13):
            self._special_key_map[f'f{i}'] = getattr(keyboard.Key, f'f{i}')
            # 同时支持不带Key前缀的形式
            self._special_key_map[f'Key.f{i}'] = getattr(keyboard.Key, f'f{i}')
    
    # -------------------------------------------------------------------------
    # 公共接口
    # -------------------------------------------------------------------------
    
    def play(self, 
             actions: List[MouseAction], 
             speed: float = 1.0,
             loop_count: int = 1,
             infinite_loop: bool = False):
        """
        开始回放（在后台线程执行）
        
        参数：
            actions: 动作列表
            speed: 回放速度倍率
            loop_count: 循环次数
            infinite_loop: 是否无限循环
        """
        if self._is_playing:
            return
        
        if not actions:
            if self.on_error:
                self.on_error("脚本为空，无法回放")
            return
        
        self._is_playing = True
        self._stop_requested = False
        self._is_paused = False
        self._pause_event.set()
        
        # 启动回放线程
        self._play_thread = threading.Thread(
            target=self._play_loop,
            args=(actions, speed, loop_count, infinite_loop),
            daemon=True
        )
        self._play_thread.start()
        
        if self.on_start:
            self.on_start()
    
    def stop(self):
        """停止回放"""
        if not self._is_playing:
            return
        
        self._stop_requested = True
        self._pause_event.set()  # 确保暂停被解除以便退出
        
        # 等待线程结束
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1.0)
        
        self._is_playing = False
        self._is_paused = False
        
        if self.on_stop:
            self.on_stop()
    
    def is_playing(self) -> bool:
        """返回是否正在回放"""
        return self._is_playing
    
    def is_paused(self) -> bool:
        """返回是否处于暂停状态"""
        return self._is_paused
    
    def request_stop(self):
        """请求停止（异步）"""
        self._stop_requested = True
    
    def pause(self):
        """暂停回放"""
        if not self._is_playing or self._is_paused:
            return
        self._is_paused = True
        self._pause_event.clear()
    
    def resume(self):
        """继续回放"""
        if not self._is_playing or not self._is_paused:
            return
        self._is_paused = False
        self._pause_event.set()
    
    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------
    
    def _play_loop(self, 
                   actions: List[MouseAction], 
                   speed: float,
                   loop_count: int,
                   infinite_loop: bool):
        """
        回放循环（在后台线程运行）
        """
        total_actions = len(actions)
        current_loop = 0
        start_time = time.time()
        
        # 获取第一个动作的坐标（用于初始化鼠标位置）
        first_x, first_y = 0, 0
        if actions:
            first_x = max(0, min(actions[0].x, self._screen_width - 1))
            first_y = max(0, min(actions[0].y, self._screen_height - 1))
        
        try:
            while True:
                # 检查是否需要停止
                if self._stop_requested:
                    break

                # 检查循环次数
                if not infinite_loop:
                    if current_loop >= loop_count:
                        break

                # 通知循环开始（按次数回放时显示进度）
                if self.on_loop_start:
                    if infinite_loop:
                        self.on_loop_start(current_loop + 1, 0)
                    else:
                        self.on_loop_start(current_loop + 1, loop_count)

                # 每次循环开始前，先将鼠标移动到录制起始位置
                if actions:
                    pyautogui.moveTo(first_x, first_y, duration=0)

                # 遍历每个动作
                for idx, action in enumerate(actions):
                    if self._stop_requested:
                        break
                    
                    # 等待时间间隔
                    if action.interval > 0:
                        actual_interval = action.interval / max(speed, 0.01)
                        self._smart_sleep(actual_interval)
                    
                    if self._stop_requested:
                        break
                    
                    # 执行动作
                    self._execute_action(action)
                    
                    # 更新进度
                    elapsed = time.time() - start_time
                    if self.on_progress:
                        self.on_progress(idx + 1, total_actions, elapsed)
                
                if self._stop_requested:
                    break
                
                current_loop += 1
        
        except pyautogui.FailSafeException:
            if self.on_error:
                self.on_error("检测到紧急停止（鼠标移至屏幕左上角）")
        
        except Exception as e:
            if self.on_error:
                self.on_error(f"回放出错: {str(e)}")
        
        finally:
            self._is_playing = False
            if self.on_stop:
                self.on_stop()
    
    def _smart_sleep(self, seconds: float):
        """
        智能休眠：高精度等待，同时支持暂停和停止
        采用"长睡 + 短周期忙等"策略，减少累积误差
        """
        if seconds <= 0:
            return
        
        end_time = time.perf_counter() + seconds
        
        # 长睡阶段：一次性睡大部分时间，减去30ms余量用于精确校准
        long_sleep = seconds - 0.03
        if long_sleep > 0:
            # 分段长睡，每0.1秒检查一次暂停/停止
            remaining_long = long_sleep
            while remaining_long > 0:
                if self._stop_requested:
                    return
                self._pause_event.wait()
                if self._stop_requested:
                    return
                chunk = min(0.1, remaining_long)
                time.sleep(chunk)
                remaining_long -= chunk
        
        # 忙等阶段：最后约30ms用高精度忙等，确保时间准确
        # 每1ms检查一次暂停/停止（减少检查频率以降低开销）
        last_check = time.perf_counter()
        while time.perf_counter() < end_time:
            now = time.perf_counter()
            if now - last_check >= 0.005:
                if self._stop_requested:
                    return
                if not self._pause_event.is_set():
                    # 进入暂停，等待恢复后重新计算结束时间
                    self._pause_event.wait()
                    if self._stop_requested:
                        return
                    pause_duration = time.perf_counter() - now
                    end_time += pause_duration
                last_check = now
    
    def _execute_action(self, action: MouseAction):
        """
        执行单个键鼠动作
        
        参数：
            action: 动作对象
        """
        # 检查坐标是否在屏幕范围内（仅鼠标动作需要）
        x, y = action.x, action.y
        if action.action_subtype != "keyboard" and action.action_type != "key_press" and action.action_type != "key_release":
            if not self._is_coord_valid(action.x, action.y):
                x = max(0, min(action.x, self._screen_width - 1))
                y = max(0, min(action.y, self._screen_height - 1))
        
        # 根据动作类型执行相应操作
        try:
            # 键盘动作
            if action.action_type == "key_press":
                self._execute_key_action(action, is_press=True)
                return
            
            if action.action_type == "key_release":
                self._execute_key_action(action, is_press=False)
                return
            
            # 鼠标动作
            if action.action_type == MouseActionType.MOVE.value:
                pyautogui.moveTo(x, y, duration=0)
            
            elif action.action_type == MouseActionType.LEFT_CLICK.value:
                pyautogui.click(x, y, button="left")
            
            elif action.action_type == MouseActionType.LEFT_DOUBLE.value:
                pyautogui.doubleClick(x, y, button="left")
            
            elif action.action_type == MouseActionType.RIGHT_CLICK.value:
                pyautogui.click(x, y, button="right")
            
            elif action.action_type == MouseActionType.LEFT_DRAG.value:
                pyautogui.dragTo(x, y, button="left", duration=0)
            
            elif action.action_type == MouseActionType.RIGHT_DRAG.value:
                pyautogui.dragTo(x, y, button="right", duration=0)
            
            elif action.action_type == MouseActionType.SCROLL.value:
                # 滚轮回放：使用与录制端完全相同的 pynput API
                # 录制时每个 on_scroll(dx, dy) 独立记录为一条动作，
                # 回放时直接对该动作调用一次 Controller.scroll(scroll_dx, scroll_dy)
                # 两者使用的底层 API 和参数完全一致，保证滚动距离严格匹配
                self._mouse_controller.scroll(action.scroll_dx, action.scroll_dy)
            
            elif action.action_type == MouseActionType.KEYFRAME.value:
                # 关键帧只做标记，不执行实际操作
                pass
        
        except pyautogui.FailSafeException:
            raise
        
        except Exception as e:
            raise RuntimeError(f"执行动作失败: {e}")
    
    def _execute_key_action(self, action: MouseAction, is_press: bool):
        """
        执行键盘按键动作
        
        参数：
            action: 动作对象
            is_press: True按下，False释放
        """
        key_identifier = action.key
        
        if not key_identifier:
            return
        
        try:
            # 先尝试作为特殊键处理
            if key_identifier in self._special_key_map:
                key_obj = self._special_key_map[key_identifier]
                if is_press:
                    self._keyboard_controller.press(key_obj)
                else:
                    self._keyboard_controller.release(key_obj)
                return
            
            # 普通字符键
            if len(key_identifier) == 1:
                if is_press:
                    self._keyboard_controller.press(key_identifier)
                else:
                    self._keyboard_controller.release(key_identifier)
                return
            
            # 作为退格键处理
            if key_identifier in ('backspace', 'Key.backspace'):
                if is_press:
                    self._keyboard_controller.press(keyboard.Key.backspace)
                else:
                    self._keyboard_controller.release(keyboard.Key.backspace)
                return
            
            # 其他特殊键名（如Key.enter, Key.space等带Key前缀）
            if key_identifier.startswith('Key.'):
                key_name = key_identifier[4:]
                if key_name in self._special_key_map:
                    key_obj = self._special_key_map[key_name]
                    if is_press:
                        self._keyboard_controller.press(key_obj)
                    else:
                        self._keyboard_controller.release(key_obj)
                    return
            
            # 使用VK码
            if action.key_code and action.key_code > 0:
                try:
                    vk_key = keyboard.KeyCode.from_vk(action.key_code)
                    if is_press:
                        self._keyboard_controller.press(vk_key)
                    else:
                        self._keyboard_controller.release(vk_key)
                    return
                except Exception:
                    pass
            
            # 最后尝试直接按键（可能是未识别的特殊键）
            try:
                if is_press:
                    self._keyboard_controller.press(key_identifier)
                else:
                    self._keyboard_controller.release(key_identifier)
            except Exception:
                pass
        
        except Exception:
            pass
    
    def _is_coord_valid(self, x: int, y: int) -> bool:
        """检查坐标是否在屏幕范围内"""
        return 0 <= x < self._screen_width and 0 <= y < self._screen_height


# ================================================================================
# 第四层：UI界面层 - tkinter GUI界面
# ================================================================================

class MouseRecorderApp:
    """
    键鼠录制回放工具主应用
    
    功能：
        - 简约清晰的中文GUI界面
        - 状态指示灯：录制红、回放绿、待机灰
        - 分区布局：状态显示区、功能按钮区、速度/循环设置区、脚本操作区
        - 全局快捷键支持
        - 鼠标/键盘动作同时录制和回放
    """
    
    def __init__(self):
        """初始化应用"""
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("鼠小侠-曦微出品自动点击器")
        
        # 窗口尺寸
        window_width = 360
        window_height = 620
        
        # 居中显示：获取屏幕尺寸后计算中心坐标
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        center_x = (screen_width - window_width) // 2
        center_y = (screen_height - window_height) // 2
        
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        self.root.resizable(False, False)
        
        # 设置窗口图标（如果存在）
        self._set_window_icon()
        
        # 应用状态
        self.state = AppState.IDLE
        self.actions: List[MouseAction] = []
        self.record_start_time: float = 0
        self.record_elapsed_time: float = 0
        
        # 创建各层组件
        self.storage = ScriptStorage()
        self.listener = MouseEventListener(
            on_action_callback=self._on_action_recorded,
            on_start_callback=self._on_recording_started,
            on_stop_callback=self._on_recording_stopped
        )
        self.player = ActionPlayer(
            on_progress_callback=self._on_play_progress,
            on_start_callback=self._on_play_started,
            on_stop_callback=self._on_play_stopped,
            on_error_callback=self._on_play_error,
            on_loop_start_callback=self._on_loop_start
        )
        
        # 全局快捷键监听器
        self._hotkey_listener: Optional[keyboard.GlobalHotKeys] = None
        
        # 构建UI
        self._build_ui()
        
        # 启动全局快捷键
        self._start_hotkey_listener()
        
        # 启动状态更新定时器
        self._start_status_updater()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
    
    # -------------------------------------------------------------------------
    # UI构建方法
    # -------------------------------------------------------------------------
    
    def _set_window_icon(self):
        """设置窗口图标"""
        # 兼容PyInstaller打包后的临时目录
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass
    
    def _build_ui(self):
        """构建UI界面"""
        # 主容器
        main_frame = tk.Frame(self.root, padx=8, pady=6)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. 功能按钮区（最上面）
        self._build_button_area(main_frame)
        
        # 2. 隐藏/显示切换按钮
        self.btn_toggle = tk.Button(
            main_frame, text="▼ 展开详细信息", 
            font=("微软雅黑", 9),
            bg="#545454", fg="white",
            activebackground="#707070",
            cursor="hand2",
            relief="flat",
            height=1,
            command=self._on_toggle_detail
        )
        self.btn_toggle.pack(fill=tk.X, pady=(0, 5))
        
        # 3. 可折叠的详细信息区域
        self._detail_frame = tk.Frame(main_frame)
        self._detail_frame.pack(fill=tk.BOTH, expand=True)
        
        # 状态显示区
        self._status_frame = self._build_status_area(self._detail_frame)
        
        # 速度/循环设置区
        self._settings_frame = self._build_settings_area(self._detail_frame)
        
        # 脚本操作区
        self._script_frame = self._build_script_area(self._detail_frame)
        
        # 日志显示区
        self._log_frame = self._build_log_area(self._detail_frame)
        
        # 默认隐藏详细信息
        self._is_detail_visible = False
        self._toggle_detail()
    
    def _on_toggle_detail(self):
        """切换详细信息的显示/隐藏"""
        self._is_detail_visible = not self._is_detail_visible
        self._toggle_detail()
    
    def _toggle_detail(self):
        """实际执行显示/隐藏操作（始终保持窗口居中）"""
        # 获取屏幕尺寸
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        if self._is_detail_visible:
            # 显示详细信息
            self._detail_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_toggle.configure(text="▲ 隐藏详细信息")
            w, h = 360, 620
        else:
            # 隐藏详细信息
            self._detail_frame.pack_forget()
            self.btn_toggle.configure(text="▼ 展开详细信息")
            w, h = 360, 180
        
        # 按新尺寸重新居中显示
        center_x = (screen_width - w) // 2
        center_y = (screen_height - h) // 2
        self.root.geometry(f"{w}x{h}+{center_x}+{center_y}")
    
    def _build_status_area(self, parent):
        """构建状态显示区"""
        frame = tk.LabelFrame(parent, text="状态显示", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 状态指示灯和文字
        status_row = tk.Frame(frame)
        status_row.pack(fill=tk.X)
        
        # 状态指示灯（Canvas绘制圆形）
        self.status_canvas = tk.Canvas(status_row, width=24, height=24, 
                                        highlightthickness=0, bg=frame.cget("bg"))
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 8))
        self.status_light = self.status_canvas.create_oval(4, 4, 20, 20, fill="#808080", outline="#606060")
        
        # 状态文字
        self.status_label = tk.Label(status_row, text="待机中", font=("微软雅黑", 11, "bold"))
        self.status_label.pack(side=tk.LEFT)
        
        # 录制信息
        info_row = tk.Frame(frame)
        info_row.pack(fill=tk.X, pady=(8, 0))
        
        # 录制时长
        tk.Label(info_row, text="录制时长：", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        self.time_label = tk.Label(info_row, text="00:00:00", font=("微软雅黑", 9, "bold"), fg="#333")
        self.time_label.pack(side=tk.LEFT)
        
        tk.Label(info_row, text="    操作步数：", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        self.step_label = tk.Label(info_row, text="0", font=("微软雅黑", 9, "bold"), fg="#333")
        self.step_label.pack(side=tk.LEFT)
        
        # 回放进度
        progress_row = tk.Frame(frame)
        progress_row.pack(fill=tk.X, pady=(8, 0))
        
        tk.Label(progress_row, text="回放进度：", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        self.progress_label = tk.Label(progress_row, text="0/0", font=("微软雅黑", 9, "bold"), fg="#333")
        self.progress_label.pack(side=tk.LEFT)
        
        tk.Label(progress_row, text="    回放耗时：", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        self.play_time_label = tk.Label(progress_row, text="00:00:00", font=("微软雅黑", 9, "bold"), fg="#333")
        self.play_time_label.pack(side=tk.LEFT)
        
        return frame
    
    def _build_button_area(self, parent):
        """构建功能按钮区（2行3列等宽布局）"""
        frame = tk.LabelFrame(parent, text="功能操作", padx=8, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 使用 grid 让 6 个按钮等宽分两行三列
        # 配置每列等宽拉伸
        frame.grid_columnconfigure(0, weight=1, uniform="btn_col")
        frame.grid_columnconfigure(1, weight=1, uniform="btn_col")
        frame.grid_columnconfigure(2, weight=1, uniform="btn_col")
        
        # 按钮样式：缩小字体（小一号），让 6 个按钮能完整显示
        btn_config = {
            "font": ("微软雅黑", 9),
            "height": 1,
            "cursor": "hand2",
            "relief": "flat",
            "bd": 0
        }
        
        # 第一行
        self.btn_record = tk.Button(
            frame, text="开始录制 (F7 )",
            bg="#67C23A", fg="white",
            activebackground="#85CE61",
            command=self._on_record_click,
            **btn_config
        )
        self.btn_record.grid(row=0, column=0, padx=3, pady=3, sticky="nsew")

        self.btn_stop_record = tk.Button(
            frame, text="停止录制 (F8 )",
            bg="#E6A23C", fg="white",
            activebackground="#EBB563",
            command=self._on_stop_record_click,
            **btn_config
        )
        self.btn_stop_record.grid(row=0, column=1, padx=3, pady=3, sticky="nsew")

        self.btn_save = tk.Button(
            frame, text="保存脚本 (F9 )",
            bg="#1F8FE8", fg="white",
            activebackground="#4DA3F0",
            command=self._on_save_script,
            **btn_config
        )
        self.btn_save.grid(row=0, column=2, padx=3, pady=3, sticky="nsew")

        # 第二行
        self.btn_play = tk.Button(
            frame, text="开始回放 (F10)",
            bg="#409EFF", fg="white",
            activebackground="#66B1FF",
            command=self._on_play_click,
            **btn_config
        )
        self.btn_play.grid(row=1, column=0, padx=3, pady=3, sticky="nsew")

        self.btn_pause_play = tk.Button(
            frame, text="暂停回放 (F11)",
            bg="#9B59B6", fg="white",
            activebackground="#B07CC6",
            command=self._on_pause_play_click,
            **btn_config
        )
        self.btn_pause_play.grid(row=1, column=1, padx=3, pady=3, sticky="nsew")

        self.btn_stop_play = tk.Button(
            frame, text="停止回放 (F12)",
            bg="#F56C6C", fg="white",
            activebackground="#F78989",
            command=self._on_stop_play_click,
            **btn_config
        )
        self.btn_stop_play.grid(row=1, column=2, padx=3, pady=3, sticky="nsew")
    
    def _build_settings_area(self, parent):
        """构建循环设置区（紧凑布局）"""
        frame = tk.LabelFrame(parent, text="回放设置", padx=8, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 循环设置
        loop_row = tk.Frame(frame)
        loop_row.pack(fill=tk.X, pady=2)

        lbl_loop = tk.Label(loop_row, text="循环模式：", font=("微软雅黑", 8))
        lbl_loop.pack(side=tk.LEFT)

        self.loop_var = tk.StringVar(value="1")
        self.loop_mode_var = tk.StringVar(value="count")  # count / infinite / custom

        rb_single = tk.Radiobutton(
            loop_row, text="单次", value="count",
            variable=self.loop_mode_var,
            font=("微软雅黑", 8),
            padx=2,
            command=self._on_loop_mode_change
        )
        rb_single.pack(side=tk.LEFT, padx=4)

        rb_infinite = tk.Radiobutton(
            loop_row, text="无限循环", value="infinite",
            variable=self.loop_mode_var,
            font=("微软雅黑", 8),
            padx=2,
            command=self._on_loop_mode_change
        )
        rb_infinite.pack(side=tk.LEFT, padx=4)

        rb_custom = tk.Radiobutton(
            loop_row, text="次数", value="custom",
            variable=self.loop_mode_var,
            font=("微软雅黑", 8),
            padx=2,
            command=self._on_loop_mode_change
        )
        rb_custom.pack(side=tk.LEFT, padx=4)

        self.loop_entry = tk.Entry(loop_row, width=4, font=("微软雅黑", 8), textvariable=self.loop_var, state=tk.DISABLED)
        self.loop_entry.pack(side=tk.LEFT, padx=2)
        
        return frame
    
    def _build_script_area(self, parent):
        """构建脚本操作区"""
        frame = tk.LabelFrame(parent, text="脚本管理", padx=10, pady=8)
        frame.pack(fill=tk.X, pady=(0, 10))

        row = tk.Frame(frame)
        row.pack(fill=tk.X)

        tk.Label(row, text="脚本列表：", font=("微软雅黑", 9), fg="#666").pack(side=tk.LEFT, padx=(0, 4))

        content_frame = tk.Frame(row)
        content_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        content_frame.grid_columnconfigure(0, weight=1, uniform="script_col")
        content_frame.grid_columnconfigure(1, weight=1, uniform="script_col")
        content_frame.grid_columnconfigure(2, weight=1, uniform="script_col")
        content_frame.grid_columnconfigure(3, weight=1, uniform="script_col")

        self.script_var = tk.StringVar()
        self.script_combobox = ttk.Combobox(
            content_frame, textvariable=self.script_var,
            font=("微软雅黑", 9),
            state="readonly", cursor="hand2"
        )
        self.script_combobox.grid(row=0, column=0, padx=(0, 4), sticky="nsew")
        self.script_combobox.bind("<<ComboboxSelected>>", self._on_script_selected)

        action_btn_config = {
            "font": ("微软雅黑", 9),
            "cursor": "hand2",
            "relief": "flat",
            "bd": 0
        }

        tk.Button(
            content_frame, text="加载",
            bg="#67C23A", fg="white",
            activebackground="#85CE61",
            command=self._on_load_from_file,
            **action_btn_config
        ).grid(row=0, column=1, padx=2, sticky="nsew")

        tk.Button(
            content_frame, text="重命名",
            bg="#E6A23C", fg="white",
            activebackground="#EBB563",
            command=self._on_rename_script,
            **action_btn_config
        ).grid(row=0, column=2, padx=2, sticky="nsew")

        tk.Button(
            content_frame, text="删除",
            bg="#F56C6C", fg="white",
            activebackground="#F78989",
            command=self._on_delete_script,
            **action_btn_config
        ).grid(row=0, column=3, padx=(2, 0), sticky="nsew")

        self._load_script_list()

        return frame
    
    def _build_log_area(self, parent):
        """构建日志显示区"""
        frame = tk.LabelFrame(parent, text="运行日志", padx=10, pady=8)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 日志文本框
        self.log_text = tk.Text(
            frame, height=8, wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#1E1E1E", fg="#D4D4D4",
            insertbackground="white",
            relief="flat"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 禁止编辑
        self.log_text.configure(state=tk.DISABLED)
        
        return frame
    
    # -------------------------------------------------------------------------
    # 状态更新方法
    # -------------------------------------------------------------------------
    
    def _update_status_light(self, state: AppState):
        """更新状态指示灯颜色"""
        color_map = {
            AppState.IDLE: "#808080",      # 灰色
            AppState.RECORDING: "#F56C6C", # 红色
            AppState.PLAYING: "#67C23A"    # 绿色
        }
        color = color_map.get(state, "#808080")
        self.status_canvas.itemconfig(self.status_light, fill=color)
    
    def _update_status_text(self, text: str):
        """更新状态文字"""
        self.status_label.configure(text=text)
    
    def _update_step_count(self):
        """更新步数显示"""
        if hasattr(self, 'step_label') and self.step_label is not None:
            self.step_label.configure(text=str(len(self.actions)))
    
    def _update_time_display(self, seconds: float):
        """更新时间显示"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        time_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        self.time_label.configure(text=time_str)
    
    def _log(self, message: str):
        """添加日志"""
        if not hasattr(self, 'log_text') or self.log_text is None:
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_line)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def _hide_window(self):
        """隐藏主窗口"""
        self.root.withdraw()
    
    def _show_window(self):
        """显示主窗口"""
        self.root.deiconify()

    # -------------------------------------------------------------------------
    # 事件处理方法
    # -------------------------------------------------------------------------

    
    def _show_countdown(self, count: int, callback: callable):
        """
        显示倒计时动画（带圈红色数字）
        
        参数：
            count: 当前倒计时数字（1-3）
            callback: 倒计时结束后的回调函数
        """
        if count <= 0:
            # 倒计时结束，销毁倒计时窗口
            if hasattr(self, '_countdown_window') and self._countdown_window:
                self._countdown_window.destroy()
                self._countdown_window = None
            # 执行回调
            if callback:
                callback()
            return
        
        # 带圈 Unicode 数字映射表（1→①, 2→②, 3→③）
        circled_digits = {
            1: "①",
            2: "②",
            3: "③"
        }
        display_text = circled_digits.get(count, str(count))
        
        # 创建或更新倒计时窗口
        if not hasattr(self, '_countdown_window') or not self._countdown_window:
            self._countdown_window = tk.Toplevel(self.root)
            self._countdown_window.overrideredirect(True)  # 无边框
            self._countdown_window.attributes("-transparentcolor", "#1a1a1a")  # 透明背景
            
            # 获取屏幕尺寸
            screen_width = self._countdown_window.winfo_screenwidth()
            screen_height = self._countdown_window.winfo_screenheight()
            
            # 窗口尺寸
            window_size = 240
            
            # 居中显示
            x = (screen_width - window_size) // 2
            y = (screen_height - window_size) // 2
            
            self._countdown_window.geometry(f"{window_size}x{window_size}+{x}+{y}")
            self._countdown_window.configure(bg="#1a1a1a")
            
            # 创建带圈红色数字标签
            self._countdown_label = tk.Label(
                self._countdown_window,
                text=display_text,
                font=("微软雅黑", 110, "bold"),
                fg="#FF0000",   # 红色字体
                bg="#1a1a1a"    # 透明背景色
            )
            self._countdown_label.pack(expand=True)
        else:
            # 更新数字（保持带圈红色字体）
            self._countdown_label.configure(text=display_text)
        
        # 1秒后继续倒计时
        self._countdown_window.after(1000, lambda: self._show_countdown(count - 1, callback))
    
    def _on_record_click(self):
        """点击开始录制按钮"""
        if self.state == AppState.PLAYING:
            self._log("正在回放中，请先停止回放")
            return
        
        if self.state == AppState.RECORDING:
            self._log("已在录制中")
            return
        
        # 清空之前的录制
        self.actions = []
        self._update_step_count()
        
        # 隐藏主窗口
        self.root.withdraw()
        
        # 显示3秒倒计时动画
        self._log("3秒后开始录制，请准备...")
        self._show_countdown(3, self._start_recording)
    
    def _start_recording(self):
        """实际开始录制"""
        self.state = AppState.RECORDING
        self.record_start_time = time.time()
        self.listener.start_recording(ignore_duration_ms=500)
        
        self._update_status_light(AppState.RECORDING)
        self._update_status_text("录制中...")
        self._log("录制已开始 (F8停止)")
    
    def _on_stop_record_click(self):
        """点击停止录制按钮"""
        if self.state != AppState.RECORDING:
            self._log("当前未在录制")
            return
        
        self.listener.stop_recording()
    
    def _on_play_click(self):
        """点击开始回放按钮"""
        if self.state == AppState.RECORDING:
            self._log("正在录制中，请先停止录制")
            return
        
        if self.state == AppState.PLAYING:
            self._log("已在回放中")
            return
        
        if not self.actions:
            self._log("脚本为空，无法回放")
            return
        
        # 获取设置
        speed = 1.0
        loop_mode = self.loop_mode_var.get()
        infinite = loop_mode == "infinite"
        
        if loop_mode == "count":
            loop_count = 1
        else:
            try:
                loop_count = int(self.loop_var.get())
                if loop_count < 1:
                    loop_count = 1
            except ValueError:
                loop_count = 1
        
        # 开始回放
        self.state = AppState.PLAYING
        self.player.play(
            self.actions, 
            speed=speed, 
            loop_count=loop_count, 
            infinite_loop=infinite
        )
        
        self._update_status_light(AppState.PLAYING)
        self._update_status_text("回放中...")
        
        loop_info = "无限循环" if infinite else ("单次" if loop_mode == "count" else f"{loop_count}次")
        self._log(f"开始回放 - {loop_info}")
        self._hide_window()
    
    def _on_stop_play_click(self):
        """点击停止回放按钮"""
        if self.state != AppState.PLAYING:
            self._log("当前未在回放")
            return
        
        self.player.stop()
    
    def _on_clear_click(self):
        """点击清空记录按钮"""
        if self.state == AppState.RECORDING:
            self._log("请先停止录制")
            return
        
        if self.state == AppState.PLAYING:
            self._log("请先停止回放")
            return
        
        self.actions = []
        self._update_step_count()
        self._log("已清空所有记录")
    
    def _on_pause_play_click(self):
        """点击暂停/继续回放按钮"""
        if not self.player.is_playing():
            self._log("当前未在回放")
            return
        
        if self.player.is_paused():
            self.player.resume()
            self._update_status_text("回放中...")
            self.btn_pause_play.configure(text="暂停回放 (F11)")
            self._log("回放已继续")
            self._hide_window()
        else:
            self.player.pause()
            self._update_status_text("已暂停")
            self.btn_pause_play.configure(text="继续回放 (F11)")
            self._log("回放已暂停")
            self._show_window()
    
    def _on_loop_mode_change(self):
        """循环模式改变"""
        if self.loop_mode_var.get() == "custom":
            self.loop_entry.configure(state=tk.NORMAL)
        else:
            self.loop_entry.configure(state=tk.DISABLED)
    
    def _on_save_script(self):
        """保存脚本"""
        if self.state != AppState.IDLE:
            self._log("请先停止录制或回放")
            return
        
        if not self.actions:
            self._log("脚本为空，无需保存")
            return
        
        script_dir = self._get_script_dir()
        filepath = filedialog.asksaveasfilename(
            title="保存脚本",
            defaultextension=".mrs",
            initialfile=f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mrs",
            filetypes=[("鼠小侠脚本", "*.mrs"), ("所有文件", "*.*")],
            initialdir=script_dir
        )
        
        if not filepath:
            return
        
        if self.storage.save_script(filepath, self.actions):
            self._log(f"脚本已保存: {os.path.basename(filepath)}")
            self._refresh_script_list()
            idx = self.script_combobox["values"].index(os.path.basename(filepath)) if os.path.basename(filepath) in self.script_combobox["values"] else -1
            if idx >= 0:
                self.script_combobox.current(idx)
        else:
            messagebox.showerror("保存失败", "保存脚本时发生错误")
    
    def _on_load_script(self):
        """从外部选择并加载脚本（保留接口，已不绑定按钮）"""
        if self.state != AppState.IDLE:
            self._log("请先停止录制或回放")
            return

        filepath = filedialog.askopenfilename(
            title="加载脚本",
            filetypes=[("鼠小侠脚本", "*.mrs"), ("所有文件", "*.*")]
        )

        if not filepath:
            return

        actions = self.storage.load_script(filepath)

        if actions is not None:
            self.actions = actions
            self._update_step_count()
            self._log(f"已加载脚本: {os.path.basename(filepath)}, 共{len(actions)}步")
            self._refresh_script_list()
            idx = self.script_combobox["values"].index(os.path.basename(filepath)) if os.path.basename(filepath) in self.script_combobox["values"] else -1
            if idx >= 0:
                self.script_combobox.current(idx)
        else:
            messagebox.showerror("加载失败", "脚本文件损坏或格式错误")
    
    def _get_script_dir(self):
        """获取脚本存储目录"""
        # 兼容PyInstaller打包后的临时目录
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        script_dir = os.path.join(base_dir, "scripts")
        if not os.path.exists(script_dir):
            os.makedirs(script_dir)
        return script_dir
    
    def _load_script_list(self):
        """加载脚本列表到下拉框"""
        script_dir = self._get_script_dir()
        try:
            files = [f for f in os.listdir(script_dir) if f.endswith(".mrs")]
            files.sort(key=lambda x: os.path.getmtime(os.path.join(script_dir, x)), reverse=True)
            self.script_combobox["values"] = files
            if files:
                self.script_combobox.current(0)
                first_script = files[0]
                filepath = os.path.join(script_dir, first_script)
                actions = self.storage.load_script(filepath)
                if actions is not None:
                    self.actions = actions
                    self._update_step_count()
                    self._log(f"已加载脚本: {first_script}, 共{len(actions)}步")
            else:
                self.script_combobox["values"] = ["无"]
                self.script_combobox.current(0)
        except Exception as e:
            self._log(f"加载脚本列表失败: {str(e)}")
            self.script_combobox["values"] = ["无"]
            self.script_combobox.current(0)
    
    def _refresh_script_list(self):
        """刷新脚本列表"""
        script_dir = self._get_script_dir()
        try:
            files = [f for f in os.listdir(script_dir) if f.endswith(".mrs")]
            files.sort(key=lambda x: os.path.getmtime(os.path.join(script_dir, x)), reverse=True)
            if files:
                self.script_combobox["values"] = files
            else:
                self.script_combobox["values"] = ["无"]
        except Exception:
            self.script_combobox["values"] = ["无"]
    
    def _on_script_selected(self, event):
        """选择脚本下拉列表中的脚本"""
        selected = self.script_var.get()
        if not selected or selected == "无":
            return
        
        if self.state != AppState.IDLE:
            self._log("请先停止录制或回放")
            return
        
        script_dir = self._get_script_dir()
        filepath = os.path.join(script_dir, selected)
        
        actions = self.storage.load_script(filepath)
        if actions is not None:
            self.actions = actions
            self._update_step_count()
            self._log(f"已加载脚本: {selected}, 共{len(actions)}步")
        else:
            messagebox.showerror("加载失败", "脚本文件损坏或格式错误")
            self._refresh_script_list()
    
    def _on_load_from_file(self):
        """从外部文件加载脚本"""
        if self.state != AppState.IDLE:
            self._log("请先停止录制或回放")
            return
        
        filepath = filedialog.askopenfilename(
            title="选择脚本文件",
            filetypes=[("MRS脚本文件", "*.mrs"), ("所有文件", "*.*")]
        )
        
        if not filepath:
            return
        
        actions = self.storage.load_script(filepath)
        if actions is not None:
            self.actions = actions
            self._update_step_count()
            filename = os.path.basename(filepath)
            self._log(f"已加载脚本: {filename}, 共{len(actions)}步")
            
            script_dir = self._get_script_dir()
            dest_path = os.path.join(script_dir, filename)
            
            filepath_norm = os.path.normpath(os.path.abspath(filepath)).lower()
            dest_path_norm = os.path.normpath(os.path.abspath(dest_path)).lower()
            
            if filepath_norm != dest_path_norm:
                try:
                    shutil.copy2(filepath, dest_path)
                    self._refresh_script_list()
                    values = list(self.script_combobox["values"])
                    if filename in values:
                        idx = values.index(filename)
                        self.script_combobox.current(idx)
                except Exception as e:
                    self._log(f"复制脚本到本地目录失败: {str(e)}")
            else:
                self._refresh_script_list()
                values = list(self.script_combobox["values"])
                if filename in values:
                    idx = values.index(filename)
                    self.script_combobox.current(idx)
        else:
            messagebox.showerror("加载失败", "脚本文件损坏或格式错误")
    
    def _on_delete_script(self):
        """删除选中的脚本"""
        selected = self.script_var.get()
        if not selected or selected == "无":
            messagebox.showwarning("提示", "请先选择一个脚本")
            return
        
        result = messagebox.askyesno(
            title="确认删除",
            message=f"确定要删除脚本 '{selected}' 吗？\n此操作不可撤销。",
            default=messagebox.NO
        )
        
        if not result:
            return
        
        script_dir = self._get_script_dir()
        filepath = os.path.join(script_dir, selected)
        
        try:
            os.remove(filepath)
            self._log(f"已删除脚本: {selected}")
            self._refresh_script_list()
            if self.script_combobox["values"]:
                self.script_combobox.current(0)
        except Exception as e:
            messagebox.showerror("删除失败", f"删除脚本时发生错误: {str(e)}")
    
    def _on_rename_script(self):
        """重命名选中的脚本"""
        selected = self.script_var.get()
        if not selected or selected == "无":
            messagebox.showwarning("提示", "请先选择一个脚本")
            return
        
        new_name = simpledialog.askstring(
            title="重命名脚本",
            prompt="请输入新的脚本名称：",
            initialvalue=os.path.splitext(selected)[0]
        )
        
        if not new_name:
            return
        
        if not new_name.strip():
            messagebox.showwarning("提示", "脚本名称不能为空")
            return
        
        script_dir = self._get_script_dir()
        old_path = os.path.join(script_dir, selected)
        new_path = os.path.join(script_dir, new_name.strip() + ".mrs")
        
        if os.path.exists(new_path):
            messagebox.showwarning("提示", "该名称的脚本已存在")
            return
        
        try:
            os.rename(old_path, new_path)
            self._log(f"脚本已重命名: {selected} -> {new_name}.mrs")
            self._refresh_script_list()
            idx = self.script_combobox["values"].index(new_name.strip() + ".mrs") if new_name.strip() + ".mrs" in self.script_combobox["values"] else -1
            if idx >= 0:
                self.script_combobox.current(idx)
        except Exception as e:
            messagebox.showerror("重命名失败", f"重命名脚本时发生错误: {str(e)}")
    
    # -------------------------------------------------------------------------
    # 回调方法（由各层调用）
    # -------------------------------------------------------------------------
    
    def _on_action_recorded(self, action: MouseAction):
        """录制到新动作时的回调"""
        self.actions.append(action)
        # 在UI线程中更新显示
        self.root.after(0, self._update_step_count)
    
    def _on_recording_started(self):
        """录制开始回调"""
        pass  # 已在_on_record_click中处理
    
    def _on_recording_stopped(self):
        """录制停止回调"""
        self.state = AppState.IDLE
        self._update_status_light(AppState.IDLE)
        self._update_status_text("待机中")
        self._log(f"录制已停止, 共{len(self.actions)}步")
        self._show_window()
    
    def _on_play_started(self):
        """回放开始回调"""
        pass  # 已在_on_play_click中处理
    
    def _on_play_stopped(self):
        """回放停止回调"""
        self.state = AppState.IDLE
        self._update_status_light(AppState.IDLE)
        self._update_status_text("待机中")
        self.btn_pause_play.configure(text="暂停回放 (F11)")
        self._log("回放已停止")
        self._show_window()
    
    def _on_play_progress(self, current: int, total: int, elapsed: float):
        """回放进度回调"""
        def update():
            self.progress_label.configure(text=f"{current}/{total}")
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            secs = int(elapsed % 60)
            self.play_time_label.configure(text=f"{hours:02d}:{minutes:02d}:{secs:02d}")
        
        self.root.after(0, update)
    
    def _on_play_error(self, error_msg: str):
        """回放错误回调"""
        self.root.after(0, lambda: self._log(f"错误: {error_msg}"))

    def _on_loop_start(self, current_loop: int, total_loops: int):
        """每次循环开始回调 - 在日志中显示回放进度"""
        def update():
            try:
                if total_loops > 0:
                    self._log(f"正在回放第{current_loop}次/共{total_loops}次")
                else:
                    self._log(f"正在回放第{current_loop}次/无限循环")
            except Exception as e:
                print(f"ERROR in _on_loop_start update: {e}")
        try:
            self.root.after(0, update)
        except Exception as e:
            print(f"ERROR scheduling _on_loop_start: {e}")

    # -------------------------------------------------------------------------
    # 全局快捷键
    # -------------------------------------------------------------------------
    
    def _start_hotkey_listener(self):
        """启动全局快捷键监听"""
        try:
            self._hotkey_listener = keyboard.GlobalHotKeys({
                "<f7>": self._hotkey_start_record,
                "<f8>": self._hotkey_stop_record,
                "<f9>": self._hotkey_save_script,
                "<f10>": self._hotkey_start_play,
                "<f11>": self._hotkey_pause_play,
                "<f12>": self._hotkey_stop_play
            })
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
            self._log("全局快捷键已启用")
        except Exception as e:
            self._log(f"快捷键注册失败: {e}")
    
    def _hotkey_start_record(self):
        """F7: 开始录制"""
        self.root.after(0, self._on_record_click)

    def _hotkey_stop_record(self):
        """F8: 停止录制"""
        self.root.after(0, self._on_stop_record_click)

    def _hotkey_save_script(self):
        """F9: 保存脚本"""
        self.root.after(0, self._on_save_script)

    def _hotkey_start_play(self):
        """F10: 开始回放"""
        self.root.after(0, self._on_play_click)

    def _hotkey_stop_play(self):
        """F12: 停止回放"""
        self.root.after(0, self._on_stop_play_click)

    def _hotkey_pause_play(self):
        """F11: 暂停/继续回放"""
        self.root.after(0, self._on_pause_play_click)
    
    # -------------------------------------------------------------------------
    # 定时器
    # -------------------------------------------------------------------------
    
    def _start_status_updater(self):
        """启动状态更新定时器"""
        self._update_timer()
    
    def _update_timer(self):
        """定时更新状态"""
        if self.state == AppState.RECORDING:
            elapsed = time.time() - self.record_start_time
            self._update_time_display(elapsed)
        
        # 每100ms更新一次
        self.root.after(100, self._update_timer)
    
    # -------------------------------------------------------------------------
    # 窗口管理
    # -------------------------------------------------------------------------
    
    def _on_window_close(self):
        """窗口关闭事件 - 弹出确认对话框防止误关"""
        # 弹出确认对话框
        result = messagebox.askyesno(
            title="确认关闭",
            message="确定要关闭鼠小侠吗？\n\n当前录制/回放将会中断，未保存的脚本可能丢失。",
            default=messagebox.NO
        )
        
        # 用户点击"否"或关闭对话框，则取消关闭
        if not result:
            return
        
        # 用户确认关闭，执行清理操作
        # 停止所有操作
        if self.listener.is_recording():
            self.listener.stop_recording()
        if self.player.is_playing():
            self.player.stop()
        
        # 停止快捷键监听
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
        
        self.root.destroy()
    
    def run(self):
        """运行应用"""
        self._log(f"{APP_NAME} {APP_VERSION} 已启动")
        self._log("快捷键: F7录制 F8停止录制 F9保存 F10回放 F11暂停 F12停止")
        self.root.mainloop()


# ================================================================================
# 程序入口
# ================================================================================

def main():
    """程序入口函数"""
    try:
        app = MouseRecorderApp()
        app.run()
    except Exception as e:
        messagebox.showerror("启动错误", f"程序启动失败:\n{str(e)}")


if __name__ == "__main__":
    main()
