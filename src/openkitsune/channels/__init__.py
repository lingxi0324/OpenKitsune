"""
消息通道模块

提供多平台 IM 集成能力:
- 统一消息类型
- 通道适配器
- 消息网关
- 媒体处理
"""

from .base import ChannelAdapter, ChannelDeliveryUnavailable
from .delivery import DeliveryState, SendErrorKind, SendResult
from .gateway import MessageGateway
from .types import (
    MediaFile,
    MessageContent,
    MessageType,
    OutgoingMessage,
    UnifiedMessage,
)

__all__ = [
    # 类型
    "MessageType",
    "UnifiedMessage",
    "MessageContent",
    "MediaFile",
    "OutgoingMessage",
    # 适配器
    "ChannelAdapter",
    "ChannelDeliveryUnavailable",
    # 投递结果
    "DeliveryState",
    "SendErrorKind",
    "SendResult",
    # 网关
    "MessageGateway",
]
