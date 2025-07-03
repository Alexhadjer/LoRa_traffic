import serial
import time
import struct
import threading
import sys
from typing import Optional, Callable, Dict, Any

class E22_900T22U:
    """For E22-900T22U LoRa module, can send and recieve at the same time."""
    
    # command vars
    CMD_SET_CONFIG = 0xC0
    CMD_GET_CONFIG = 0xC1
    CMD_SET_TEMPORARY = 0xC2
    CMD_GET_VERSION = 0xC3
    CMD_RESET = 0xC4
    
    # operation modes
    MODE_NORMAL = 0
    MODE_CONFIG = 3
    
    def __init__(self, port: str, baudrate: int = 9600,
                 receive_callback: Optional[Callable[[bytes], None]] = None):
        """
        args:
            port: serial port (for us Linux default:'/dev/ttyUSB0' or windows default: 'COM3')
            baudrate: UART baud rate
            receive_callback: optional function called on incoming data
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.receive_callback = receive_callback
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_thread_running = False

    def connect(self) -> bool:
        """open serial port and start reciever in background"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1  # non-blocking read
            )
            time.sleep(0.1)
            self._start_background_receive()
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """stop receiver & close port"""
        self._stop_background_receive()
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    def _set_mode_normal(self):
        time.sleep(0.01)

    def send_data(self, data: bytes,
                  address: Optional[int] = None,
                  channel: Optional[int] = None) -> bool:
        """send data while receiver thread also runs"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return False

        self._set_mode_normal()
        try:
            if address is not None and channel is not None:
                packet = struct.pack('>HB', address, channel) + data
            else:
                packet = data
            self.serial_conn.write(packet)
            return True
        except Exception as e:
            print(f"Send error: {e}")
            return False

    def _receive_loop(self):
        """internal thread: non-blocking read and callback"""
        while self._recv_thread_running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    incoming = self.serial_conn.read(self.serial_conn.in_waiting)
                    if incoming and self.receive_callback:
                        self.receive_callback(incoming)
            except Exception as e:
                print(f"Receive error: {e}")
            time.sleep(0.01)

    def _start_background_receive(self):
        if self._recv_thread_running:
            return
        self._recv_thread_running = True
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def _stop_background_receive(self):
        self._recv_thread_running = False
        if self._recv_thread:
            self._recv_thread.join()

    def send_command(self, command: int, data: bytes = b'') -> Optional[bytes]:
        """send config command and read response"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        self._set_mode_normal()
        pkt = struct.pack('B', command) + data
        self.serial_conn.write(pkt)
        time.sleep(0.1)
        resp = b''
        while self.serial_conn.in_waiting > 0:
            resp += self.serial_conn.read(self.serial_conn.in_waiting)
            time.sleep(0.01)
        return resp

if __name__ == '__main__':
    # find serial port from CLI argument or use defaults
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        import platform
        if platform.system() == 'Windows':
            port = 'COM3'
        else:
            port = '/dev/ttyUSB0'

    # simple REPL with full duplex
    def on_receive(data: bytes):
        try:
            print(f"<RECV> {data.decode('utf-8')}")
        except UnicodeDecodeError:
            print(f"<RECV raw> {data.hex()}")

    lora = E22_900T22U(port, 9600, receive_callback=on_receive)
    if not lora.connect():
        print("Failed to connect")
        sys.exit(1)

    print(f"Connected on {port}. Type to send, Ctrl+C to exit.")
    try:
        while True:
            msg = input()
            success = lora.send_data(msg.encode('utf-8'))
            prefix = '<SEND>' if success else '<SEND failed>'
            print(f"{prefix} {msg}")
    except KeyboardInterrupt:
        print("\nDisconnecting...")
    finally:
        lora.disconnect()
