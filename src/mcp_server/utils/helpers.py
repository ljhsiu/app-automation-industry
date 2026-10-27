"""辅助函数模块"""

from typing import Any, Optional
import re


def parse_battery(battery_text: str | None) -> Optional[int]:
    """
    解析电量文本

    Args:
        battery_text: 电量文本，如 "85%" 或 "85"

    Returns:
        int: 电量值，解析失败返回 None
    """
    if not battery_text:
        return None

    # 移除 % 符号
    text = battery_text.replace('%', '').strip()

    try:
        return int(text)
    except ValueError:
        return None


def format_result(
    success: bool,
    message: str,
    data: Optional[dict] = None,
    error: Optional[str] = None
) -> dict:
    """
    格式化结果输出

    Args:
        success: 是否成功
        message: 结果消息
        data: 附加数据
        error: 错误信息

    Returns:
        dict: 格式化后的结果
    """
    result = {
        "success": success,
        "message": message
    }

    if data is not None:
        result["data"] = data

    if error is not None:
        result["error"] = error

    return result


def sanitize_error(error: Exception) -> str:
    """
    清理错误信息，移除敏感信息

    Args:
        error: 异常对象

    Returns:
        str: 清理后的错误信息
    """
    error_msg = str(error)

    # 移除可能的 IP 地址（简单的脱敏）
    # 如果需要更严格的脱敏，可以扩展这个函数
    ip_pattern = r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    error_msg = re.sub(ip_pattern, '[DEVICE_IP]', error_msg)

    return error_msg


def validate_device_ip(ip: str | None) -> bool:
    """
    验证设备 IP 格式

    Args:
        ip: IP 地址字符串

    Returns:
        bool: 是否有效
    """
    if not ip:
        return False

    # 支持 IP:Port 格式或纯 IP 格式
    parts = ip.split(':')

    # 验证 IP 部分
    ip_part = parts[0]
    ip_segments = ip_part.split('.')

    if len(ip_segments) != 4:
        return False

    for segment in ip_segments:
        try:
            num = int(segment)
            if not (0 <= num <= 255):
                return False
        except ValueError:
            return False

    # 验证端口部分（如果有）
    if len(parts) > 1:
        try:
            port = int(parts[1])
            if not (1 <= port <= 65535):
                return False
        except ValueError:
            return False

    return True


def format_duration(seconds: int) -> str:
    """
    格式化时长

    Args:
        seconds: 秒数

    Returns:
        str: 格式化后的时长字符串
    """
    if seconds < 60:
        return f"{seconds} 秒"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if minutes < 60:
        if remaining_seconds > 0:
            return f"{minutes} 分 {remaining_seconds} 秒"
        return f"{minutes} 分"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if remaining_minutes > 0:
        return f"{hours} 小时 {remaining_minutes} 分"
    return f"{hours} 小时"
