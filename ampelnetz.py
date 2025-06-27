import socket
import threading
import time
import pickle
import sys

# === LOG ===
class TrafficLog:
    def __init__(self, node_id):
        self.node_id = node_id
        self.entries = []  # (timestamp, state, node_id)

    def append(self, state):
        entry = (time.time(), state, self.node_id)
        self.entries.append(entry)

    def merge(self, other_entries):
        for entry in other_entries:
            if entry not in self.entries:
                self.entries.append(entry)
        self.entries.sort()  # Optional

    def get_latest_state(self):
        if not self.entries:
            return "UNKNOWN"
        latest = [e for e in self.entries if e[2] == self.node_id]
        return latest[-1][1] if latest else "UNKNOWN"

    def export(self):
        return pickle.dumps(self.entries)

    def import_and_merge(self, raw_data):
        try:
            other_entries = pickle.loads(raw_data)
            self.merge(other_entries)
        except Exception as e:
            print(f"[{self.node_id}] Error merging logs: {e}")


# === Kommunikation (UDP, leicht ersetzbar) ===
class UDPInterface:
    def __init__(self, listen_port, peer_addresses):
        self.listen_port = listen_port
        self.peer_addresses = peer_addresses
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", listen_port))
        self.running = True

    def send(self, data: bytes):
        for addr in self.peer_addresses:
            self.sock.sendto(data, addr)

    def receive_loop(self, callback):
        def loop():
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                    callback(data, addr)
                except:
                    continue
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.sock.close()


# === Die Ampel selbst ===
class TrafficLightNode:
    def __init__(self, node_id, comm: UDPInterface):
        self.node_id = node_id
        self.comm = comm
        self.log = TrafficLog(node_id)
        self.states = ["GREEN", "YELLOW", "RED"]
        self.running = True

    def receive(self, data, addr):
        self.log.import_and_merge(data)
        latest = self.log.entries[-1]
        print(f"[{self.node_id}] Received log entry from {latest[2]}: {latest[1]}")

    def run(self):
        self.comm.receive_loop(self.receive)
        idx = 0
        while self.running:
            state = self.states[idx]
            self.log.append(state)
            print(f"[{self.node_id}] My state: {state}")
            self.comm.send(self.log.export())
            time.sleep(3 if state == "GREEN" else 1)
            idx = (idx + 1) % len(self.states)

    def stop(self):
        self.comm.stop()
        self.running = False


# === Start über CLI ===
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 ampel.py [1|2|3]")
        sys.exit(1)

    node = int(sys.argv[1])
    ports = {1: 10001, 2: 10002, 3: 10003}
    peers = [( "127.0.0.1", ports[i]) for i in ports if i != node]

    comm = UDPInterface(listen_port=ports[node], peer_addresses=peers)
    light = TrafficLightNode(node_id=node, comm=comm)

    try:
        light.run()
    except KeyboardInterrupt:
        light.stop()
