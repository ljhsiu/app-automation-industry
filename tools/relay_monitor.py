"""
继电器状态监控脚本

功能：
- 接收继电器反馈状态：01=关机，02=开机
- 检测断电重启序列：连续收到 01 -> 02 认为重启成功
- 支持重试机制：最多 3 次失败后任务失败

使用方法：
    # 命令行直接运行
    python relay_monitor.py --port COM3 --baudrate 115200

    # 作为模块导入
    from relay_monitor import RelayMonitor

    monitor = RelayMonitor(port='COM3', baudrate=115200)
    result = monitor.wait_for_reboot(timeout=60)
"""

import serial
import socket
import threading
import time
import logging
import argparse
import queue
from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class RelayState(Enum):
    """继电器状态枚举"""
    UNKNOWN = "00"  # 未知状态
    OFF = "01"     # 关机
    ON = "02"      # 开机
    INVALID = "FF" # 无效状态


class RebootResult(Enum):
    """重启检测结果"""
    SUCCESS = True
    FAILED = False


@dataclass
class RelayMessage:
    """继电器消息"""
    state: RelayState
    raw_data: str
    timestamp: float


class CommunicationBackend(ABC):
    """通信后端抽象基类"""

    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def read_message(self, timeout: float = 1.0) -> Optional[str]:
        """读取消息"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass


class SerialBackend(CommunicationBackend):
    """串口通信后端"""

    def __init__(self, port: str, baudrate: int = 115200,
                 bytesize: int = 8, parity: str = 'N',
                 stopbits: int = 1, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None

    def connect(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.timeout
            )
            logger.info(f"串口连接成功: {self.port} @ {self.baudrate}bps")
            return True
        except serial.SerialException as e:
            logger.error(f"串口连接失败: {e}")
            return False

    def disconnect(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("串口已断开")

    def read_message(self, timeout: float = 1.0) -> Optional[str]:
        if not self.serial or not self.serial.is_open:
            return None

        try:
            # 设置单次读取超时
            self.serial.timeout = timeout
            data = self.serial.readline()
            if data:
                # 尝试解码并清理数据
                decoded = data.decode('utf-8', errors='ignore').strip()
                return decoded if decoded else None
            return None
        except Exception as e:
            logger.debug(f"读取串口数据异常: {e}")
            return None

    def is_connected(self) -> bool:
        return self.serial is not None and self.serial.is_open


class TcpBackend(CommunicationBackend):
    """TCP 通信后端"""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            logger.info(f"TCP 连接成功: {self.host}:{self.port}")
            return True
        except socket.error as e:
            logger.error(f"TCP 连接失败: {e}")
            return False

    def disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            logger.info("TCP 连接已断开")

    def read_message(self, timeout: float = 1.0) -> Optional[str]:
        if not self.socket:
            return None

        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(1024)
            if data:
                return data.decode('utf-8', errors='ignore').strip()
            return None
        except socket.timeout:
            return None
        except Exception as e:
            logger.debug(f"TCP 读取异常: {e}")
            return None

    def is_connected(self) -> bool:
        return self.socket is not None


class RelayMonitor:
    """
    继电器状态监控器

    检测机器断电重启流程：
    1. 等待接收 OFF 状态 (01)
    2. 继续等待 ON 状态 (02)
    3. 收到 OFF->ON 序列认为重启成功

    如果检测失败，自动重试，最多重试 max_retries 次
    """

    def __init__(
        self,
        backend: Optional[CommunicationBackend] = None,
        # 串口参数（兼容旧接口）
        port: Optional[str] = None,
        baudrate: int = 115200,
        # TCP 参数
        host: Optional[str] = None,
        tcp_port: Optional[int] = None,
        # 通用参数
        state_callback: Optional[Callable[[RelayState], None]] = None,
        max_retries: int = 3,
        retry_interval: float = 2.0,
        expect_off_timeout: float = 30.0,
        expect_on_timeout: float = 60.0
    ):
        """
        初始化继电器监控器

        Args:
            backend: 通信后端实例（优先级最高）
            port: 串口号，如 'COM3' 或 '/dev/ttyUSB0'
            baudrate: 串口波特率
            host: TCP 服务器地址
            tcp_port: TCP 端口
            state_callback: 状态变化回调函数
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            expect_off_timeout: 等待 OFF 状态超时时间
            expect_on_timeout: 等待 ON 状态超时时间
        """
        # 初始化通信后端
        if backend:
            self.backend = backend
        elif port:
            self.backend = SerialBackend(port, baudrate)
        elif host and tcp_port:
            self.backend = TcpBackend(host, tcp_port)
        else:
            raise ValueError("必须提供 backend、port 或 host+tcp_port")

        self.state_callback = state_callback
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        self.expect_off_timeout = expect_off_timeout
        self.expect_on_timeout = expect_on_timeout

        self._running = False
        self._message_queue: queue.Queue = queue.Queue()
        self._listener_thread: Optional[threading.Thread] = None

    def _parse_state(self, raw_message: str) -> Optional[RelayState]:
        """解析消息中的状态码"""
        raw_message = raw_message.strip().upper()

        # 支持多种格式:
        # - "01" -> OFF
        # - "02" -> ON
        # - "STATE:01" -> OFF
        # - "RELAY=02" -> ON
        # - "01,02,03" (取第一个有效状态)

        for state_code in ['01', '02']:
            if state_code in raw_message:
                return RelayState.OFF if state_code == '01' else RelayState.ON

        return None

    def _listener_worker(self):
        """消息监听工作线程"""
        logger.debug("消息监听线程启动")
        while self._running:
            message = self.backend.read_message(timeout=0.5)
            if message:
                logger.debug(f"收到原始消息: {message}")
                self._message_queue.put(message)
        logger.debug("消息监听线程退出")

    def start_listening(self):
        """开始监听消息"""
        if self._running:
            return

        if not self.backend.connect():
            raise RuntimeError("无法建立通信连接")

        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listener_worker,
            daemon=True,
            name="RelayListener"
        )
        self._listener_thread.start()
        logger.info("开始监听继电器状态")

    def stop_listening(self):
        """停止监听"""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=2.0)
        self.backend.disconnect()
        logger.info("停止监听")

    def _wait_for_state(self, expected_state: RelayState,
                       timeout: float) -> Optional[RelayMessage]:
        """等待指定状态消息"""
        start_time = time.time()
        last_state = None

        while time.time() - start_time < timeout:
            try:
                raw_message = self._message_queue.get(timeout=0.5)
                state = self._parse_state(raw_message)

                if state:
                    msg = RelayMessage(
                        state=state,
                        raw_data=raw_message,
                        timestamp=time.time()
                    )

                    # 触发回调
                    if self.state_callback:
                        self.state_callback(state)

                    # 记录最新状态
                    last_state = msg

                    # 检查是否匹配目标状态
                    if state == expected_state:
                        logger.info(f"收到期望状态: {expected_state.name} ({expected_state.value})")
                        return msg

            except queue.Empty:
                continue

        # 超时，返回最后收到的状态（如果有）
        if last_state:
            logger.warning(f"等待 {expected_state.name} 超时，最后收到: {last_state.state.name}")
        else:
            logger.warning(f"等待 {expected_state.name} 超时，未收到任何状态")
        return None

    def check_reboot_sequence(self) -> RebootResult:
        """
        检测一次完整的断电重启序列

        Returns:
            RebootResult.SUCCESS: 检测到 OFF->ON 序列
            RebootResult.FAILED: 未检测到完整序列
        """
        logger.info("=" * 50)
        logger.info("开始检测断电重启序列")
        logger.info("=" * 50)

        # 清空队列中的旧消息
        while not self._message_queue.empty():
            try:
                self._message_queue.get_nowait()
            except queue.Empty:
                break

        # 步骤1: 等待 OFF 状态 (01)
        logger.info(f"步骤1: 等待关机状态 (01)，超时 {self.expect_off_timeout}s")
        off_msg = self._wait_for_state(RelayState.OFF, self.expect_off_timeout)

        if not off_msg:
            logger.error("未收到关机状态，检测失败")
            return RebootResult.FAILED

        logger.info(f"✓ 收到关机状态: {off_msg.raw_data}")

        # 步骤2: 等待 ON 状态 (02)
        logger.info(f"步骤2: 等待开机状态 (02)，超时 {self.expect_on_timeout}s")
        on_msg = self._wait_for_state(RelayState.ON, self.expect_on_timeout)

        if not on_msg:
            logger.error("未收到开机状态，检测失败")
            return RebootResult.FAILED

        logger.info(f"✓ 收到开机状态: {on_msg.raw_data}")

        # 步骤3: 确认重启成功
        elapsed = on_msg.timestamp - off_msg.timestamp
        logger.info("=" * 50)
        logger.info(f"✓✓✓ 检测成功！机器断电重启成功")
        logger.info(f"    关机->开机 耗时: {elapsed:.1f} 秒")
        logger.info("=" * 50)

        return RebootResult.SUCCESS

    def wait_for_reboot(self, timeout: Optional[float] = None) -> dict:
        """
        等待并检测机器断电重启，带重试机制

        Args:
            timeout: 总超时时间（秒），None 表示不限制

        Returns:
            dict: {
                'success': bool,           # 整体是否成功
                'total_attempts': int,     # 总尝试次数
                'successful_attempt': int,  # 成功的尝试次数（0 或 1）
                'details': [               # 每次尝试的详情
                    {
                        'attempt': int,
                        'result': RebootResult,
                        'off_time': float,  # 收到 OFF 的时间戳
                        'on_time': float,    # 收到 ON 的时间戳
                        'elapsed': float     # 总耗时
                    }
                ]
            }
        """
        start_time = time.time()
        attempt = 0
        details = []
        success = False

        while True:
            # 检查总超时
            if timeout and (time.time() - start_time) >= timeout:
                logger.warning(f"达到总超时时间 {timeout}s，退出")
                break

            # 检查重试次数
            if attempt >= self.max_retries:
                logger.error(f"达到最大重试次数 {self.max_retries}，任务失败")
                break

            attempt += 1
            logger.info(f"\n{'='*50}")
            logger.info(f"第 {attempt}/{self.max_retries} 次尝试")
            logger.info(f"{'='*50}")

            attempt_start = time.time()
            result = self.check_reboot_sequence()

            detail = {
                'attempt': attempt,
                'result': result,
                'elapsed': time.time() - attempt_start
            }

            if result == RebootResult.SUCCESS:
                details.append(detail)
                success = True
                break
            else:
                details.append(detail)
                logger.warning(f"第 {attempt} 次尝试失败")

                # 不是最后一次，等待后重试
                if attempt < self.max_retries:
                    logger.info(f"{self.retry_interval} 秒后进行第 {attempt + 1} 次尝试...")
                    time.sleep(self.retry_interval)

        # 返回最终结果
        return {
            'success': success,
            'total_attempts': attempt,
            'successful_attempt': 1 if success else 0,
            'details': details
        }

    def __enter__(self):
        self.start_listening()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_listening()
        return False


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='继电器状态监控 - 检测机器断电重启',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 串口模式
  python relay_monitor.py --port COM3 --baudrate 115200

  # TCP 模式
  python relay_monitor.py --host 192.168.1.100 --tcp-port 8888

  # 自定义重试次数和超时
  python relay_monitor.py --port COM3 --max-retries 5 --off-timeout 60
        """
    )

    # 通信方式
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--port', '-p', help='串口号，如 COM3 或 /dev/ttyUSB0')
    mode_group.add_argument('--host', help='TCP 服务器地址')

    parser.add_argument('--baudrate', '-b', type=int, default=115200,
                       help='串口波特率 (默认: 115200)')
    parser.add_argument('--tcp-port', type=int, default=8888,
                       help='TCP 端口 (默认: 8888)')

    # 检测参数
    parser.add_argument('--max-retries', '-r', type=int, default=3,
                       help='最大重试次数 (默认: 3)')
    parser.add_argument('--retry-interval', type=float, default=2.0,
                       help='重试间隔秒数 (默认: 2.0)')
    parser.add_argument('--off-timeout', type=float, default=30.0,
                       help='等待关机状态超时 (默认: 30.0)')
    parser.add_argument('--on-timeout', type=float, default=60.0,
                       help='等待开机状态超时 (默认: 60.0)')
    parser.add_argument('--timeout', type=float, default=None,
                       help='总超时时间（秒），默认不限制')

    # 日志
    parser.add_argument('--debug', '-d', action='store_true',
                       help='启用调试日志')

    args = parser.parse_args()

    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 创建监控器
    try:
        if args.port:
            monitor = RelayMonitor(
                port=args.port,
                baudrate=args.baudrate,
                max_retries=args.max_retries,
                retry_interval=args.retry_interval,
                expect_off_timeout=args.off_timeout,
                expect_on_timeout=args.on_timeout
            )
            conn_desc = f"串口 {args.port} @ {args.baudrate}bps"
        else:
            monitor = RelayMonitor(
                host=args.host,
                tcp_port=args.tcp_port,
                max_retries=args.max_retries,
                retry_interval=args.retry_interval,
                expect_off_timeout=args.off_timeout,
                expect_on_timeout=args.on_timeout
            )
            conn_desc = f"TCP {args.host}:{args.tcp_port}"

        logger.info(f"继电器监控器初始化完成")
        logger.info(f"连接方式: {conn_desc}")
        logger.info(f"最大重试: {args.max_retries} 次")

        # 启动监听
        with monitor:
            # 执行检测
            result = monitor.wait_for_reboot(timeout=args.timeout)

            # 输出结果
            logger.info("\n" + "=" * 50)
            logger.info("最终结果")
            logger.info("=" * 50)
            logger.info(f"成功: {result['success']}")
            logger.info(f"总尝试次数: {result['total_attempts']}")

            for detail in result['details']:
                status = '✓ 成功' if detail['result'] == RebootResult.SUCCESS else '✗ 失败'
                logger.info(f"  第{detail['attempt']}次: {status} ({detail['elapsed']:.1f}s)")

            logger.info("=" * 50)

            # 设置退出码
            import sys
            sys.exit(0 if result['success'] else 1)

    except KeyboardInterrupt:
        logger.info("\n用户中断")
    except Exception as e:
        logger.error(f"执行异常: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()
