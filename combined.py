import serial
import time
import struct
import threading
import sys
import json
import os
import shutil
import uuid
from datetime import datetime
from typing import Optional, Callable

# LoRa module handler
class E22_900T22U:
    """For E22-900T22U LoRa module, can send and receive at the same time."""
    CMD_SET_CONFIG = 0xC0
    CMD_GET_CONFIG = 0xC1
    CMD_SET_TEMPORARY = 0xC2
    CMD_GET_VERSION = 0xC3
    CMD_RESET = 0xC4
    MODE_NORMAL = 0
    MODE_CONFIG = 3

    def __init__(self, port: str, baudrate: int = 9600, receive_callback: Optional[Callable[[bytes], None]] = None):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: Optional[serial.Serial] = None
        self.receive_callback = receive_callback
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_thread_running = False

    def connect(self) -> bool:
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            time.sleep(0.1)
            self._start_background_receive()
            return True
        except Exception as e:
            print(f"LoRa connection failed: {e}")
            return False

    def disconnect(self):
        self._stop_background_receive()
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    def _set_mode_normal(self):
        time.sleep(0.01)

    def send_data(self, data: bytes) -> bool:
        if not self.serial_conn or not self.serial_conn.is_open:
            return False
        self._set_mode_normal()
        try:
            self.serial_conn.write(data)
            return True
        except Exception as e:
            print(f"LoRa send error: {e}")
            return False

    def _receive_loop(self):
        while self._recv_thread_running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    incoming = self.serial_conn.read(self.serial_conn.in_waiting)
                    if incoming and self.receive_callback:
                        self.receive_callback(incoming)
            except Exception as e:
                print(f"LoRa receive error: {e}")
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


# Intersection logic using CRDT frontier

def current_timestamp() -> str:
    return datetime.now().isoformat() + ' '

def delete_files(path: str):
    if os.path.exists(path):
        shutil.rmtree(path)

class IntersectionNode:
    def __init__(self, intersection_id: str, lora_port: str, baudrate: int = 9600,
                 switch_interval: int = 12, temp: bool = False):
        self.intersection = intersection_id
        self.frontier: Dict[str, int] = {}
        self.frontier_dir = f"frontiers/{self.intersection}"
        self.switch_interval = switch_interval
        self.temp = temp
        self.last_merge_time = time.time()
        self.overload_active = False
        self.overload_road: Optional[str] = None
        self.overload_ends_at = 0
        # setup LoRa
        self.lora = E22_900T22U(lora_port, baudrate, receive_callback=self._on_receive)
        if not self.lora.connect():
            raise ConnectionError(f"Cannot connect LoRa on {lora_port}")
        # init state
        #delete_files(self.frontier_dir)  # remove for testing; remove if persistent desired
        self.load_frontier()
        print(f"[{self.intersection}] MAIN ROAD green")
        # start threads
        threading.Thread(target=self._auto_switch, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()
        # input overload
        threading.Thread(target=self._overload_input, daemon=True).start()
        self._run_intersections()
    
    def _run_intersections(self):
        global last_merge_time, overload_active, overload_road, overload_ends_at #to save when we merged last
        while True:
            time.sleep(0.1) #check very often

            #check if overload expired
            if self.overload_active:
                if time.time() >= self.overload_ends_at:
                    print(f"[{self.intersection}] Overload period ended. Resuming normal operation.")
                    self.overload_active = False
                    self.overload_road = None
                    self.overload_ends_at = 0
                    self._switch_light()

                else:
                #while in overload, keep printing the state every few seconds
                    if int(time.time() * 10) % 10 == 0:  # every 1s approx
                        self._switch_light()
                    continue  #don't run CRDT switching

            if time.time() - self.last_merge_time >= self.switch_interval: #after every switch-interval switch the traffic lights
                if self._can_switch():
                    self.frontier[self.intersection] += 1
                    self._switch_light()

    def load_frontier(self):
        self.frontier[self.intersection] = 0
        if self.temp:
            return
        os.makedirs(self.frontier_dir, exist_ok=True)
        for fname in os.listdir(self.frontier_dir):
            path = os.path.join(self.frontier_dir, fname)
            try:
                with open(path, 'r') as f:
                    cnt = int(f.read().strip())
                name = fname.replace('.txt', '')
                self.frontier[name] = cnt
            except:
                continue

    def save_frontier(self):
        if self.temp: return
        os.makedirs(self.frontier_dir, exist_ok=True)
        for name, cnt in self.frontier.items():
            with open(f"{self.frontier_dir}/{name}.txt", 'w') as f:
                f.write(str(cnt))

    def _auto_switch(self):
        while True:
            time.sleep(0.1)
            now = time.time()
            if self.overload_active:
                if now >= self.overload_ends_at:
                    print(f"[{self.intersection}] Overload ended. Resuming normal.")
                    self.overload_active = False
                    self.overload_road = None
                    self.overload_ends_at = 0
                    self._switch_light()
                else:
                    if int(now*10)%10==0:
                        self._switch_light()
                    continue
            if now - self.last_merge_time >= self.switch_interval:
                if self._can_switch():
                    self.frontier[self.intersection] += 1
                    self._switch_light()

    def _can_switch(self) -> bool:
        my = self.frontier.get(self.intersection, 0)
        return all(cnt == my for cnt in self.frontier.values())

    def _switch_light(self):
        if self.overload_active and self.overload_road:
            print(f"[{self.intersection}] OVERLOAD: Holding {self.overload_road.upper()} ROAD green")
        else:
            idx = self.frontier[self.intersection]
            state = "MAIN ROAD green" if idx % 2 == 0 else "SIDE ROAD green"
            print(f"[{self.intersection}] Switching to {state}")
        ts = datetime.now().isoformat() + " "
        with open(f"state_log_{self.intersection}.txt", "a") as logf:
            logf.write(f"{ts} | {self.intersection} | {state}\n")

        self.save_frontier()
        self.last_merge_time = time.time()

    def _send_loop(self):
        while True:
            if not self.overload_active:
                msg = json.dumps(self.frontier).encode('utf-8')
                self.lora.send_data(msg)
            time.sleep(self.switch_interval)

    def _on_receive(self, data: bytes):
        ts = datetime.now().isoformat() + " "
        raw = data.decode('utf-8', errors='ignore')
        with open(f"receive_log_{self.intersection}.txt", "a") as rlog:
            rlog.write(f"{ts} | {self.intersection} RECEIVED | {raw}\n")
        try:
            payload = data.decode('utf-8')
            received = json.loads(payload)
        except:
            return
        # overload detection
        reason = received.get('reason')
        if reason and reason.startswith('overload_'):
            road = reason.split('_')[1]
            self.overload_active = True
            self.overload_road = road
            self.overload_ends_at = time.time() + 10
            self._log_entry(received)
            print(f"[{self.intersection}] Overload signal: hold {road.upper()}")
            self._switch_light()
            return
        # normal merge
        updated = False
        for uid, cnt in received.items():
            if uid not in self.frontier or self.frontier[uid] < cnt:
                self.frontier[uid] = cnt
                updated = True
        if updated:
            my = self.frontier[self.intersection]
            others = [c for k,c in self.frontier.items() if k != self.intersection]
            mx = max(others, default=my)
            if mx > my:
                self.frontier[self.intersection] = mx
                self._switch_light()
        self._display()

    def _display(self):
        states = [f"{u}: {'MAIN' if c%2==0 else 'SIDE'} GREEN ({c})" for u,c in sorted(self.frontier.items())]
        print(f"Traffic states - {', '.join(states)}")

    def _log_entry(self, entry: dict):
        fn = f"log_{self.intersection}.txt"
        with open(fn, 'a') as f:
            f.write(json.dumps(entry)+'\n')
        self.frontier.setdefault(entry['intersection_id'], 0)
        self.save_frontier()

    def _overload_input(self):
        while True:
            cmd = input().strip().lower().split()
            if cmd and cmd[0]=='overload' and len(cmd)==2:
                road=cmd[1]
                entry = {
                    'id': str(uuid.uuid4()),
                    'intersection_id': self.intersection,
                    'state': {'main':'GREEN','side':'RED'} if road=='main' else {'main':'RED','side':'GREEN'},
                    'reason': f"overload_{road}",
                    'timestamp': current_timestamp()
                }
                self._log_entry(entry)
                self.lora.send_data(json.dumps(entry).encode('utf-8'))
                self.overload_active=True
                self.overload_road=road
                self.overload_ends_at=time.time()+10
                print(f"[{self.intersection}] Sent overload for {road.upper()}")
                self._switch_light()

if __name__ == '__main__':
    if len(sys.argv)>1:
        intersection_id=sys.argv[1]
    else:
        intersection_id='A'
    if len(sys.argv)>2:
        port=sys.argv[2]
    else:
        port='/dev/ttyUSB0'
    node = IntersectionNode(intersection_id, port)
