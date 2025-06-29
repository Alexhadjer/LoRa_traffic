import random
import socket
import json
import time
import threading
import os
import sys
import uuid
from datetime import datetime

# der Zustand wechselt abwechslungsweise von seitenstrassen und hauptstrasse, die drei kreuzungen passen sich einander an
PORT = 10000
BROADCAST_IP = "255.255.255.255" #for UDP; later change to LoRa
SIDE_GREEN_DURATION = 5

def current_timestamp(): #for creating timestamp 
    return datetime.utcnow().isoformat() + 'Z'

def deletions(intersection_id): #this only for testing every time from zero
    log_file = f"log_{intersection_id}.txt"
    frontier_file = f"frontiers_{intersection_id}.json"
    for file in [log_file, frontier_file]:
        if os.path.exists(file):
            os.remove(file)
            print(f"[{intersection_id}] Deleted: {file}")

class OfflineTrafficLight: 
    def __init__(self, intersection_id): #manage logs, ids, states
        self.intersection_id = intersection_id 
        self.logfile = f"log_{intersection_id}.txt"
        self.frontierfile = f"frontiers_{intersection_id}.json"
        self.state = {'main': 'GREEN', 'side': 'RED'}
        self.log = [] #append only logs
        self.frontiers = {} #frontiers to keep track of last seen IDs per intersection
        self.current_session_id = None
        self.last_session_time = time.time()
        self.my_turn_timeout = 10 + random.uniform(0, 3) #instead of intersectionid use random so that its nondeterministic
        self.switch_back_time = None
        self.last_received_time = 0  #timestamp of last incoming message to avoid conflicts


    def append_entry(self, entry): #append to log file and update frontiers
        with open(self.logfile, 'a') as f:
            f.write(json.dumps(entry) + "\n")
        self.log.append(entry)
        self.frontiers[entry['intersection_id']] = entry['id']
        with open(self.frontierfile, 'w') as f:
            json.dump(self.frontiers, f, indent=2) #saves the last seen messages per intersection on each frontier(for detailed comparison of last recieved messages)

    def load_state(self): #load old states if any exist
        if os.path.exists(self.logfile):
            with open(self.logfile) as f:
                self.log = [json.loads(line.strip()) for line in f if line.strip()]
                for entry in self.log:
                    self.frontiers[entry['intersection_id']] = entry['id']

class UDPCommunicator: #communication now over udp later should change to LoRa
    def __init__(self, intersection_id, handler):
        self.id = intersection_id
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", PORT))

    def send(self, entry): #sends simulated broadcast of RED,GREEN and intersectionID mainly
        data = json.dumps(entry).encode()
        self.sock.sendto(data, (BROADCAST_IP, PORT))
        print(f"[{self.id}] Broadcast sent: {entry}")

    def receive(self):
        while True:
            data, _ = self.sock.recvfrom(4096)
            msg = json.loads(data.decode())
            if msg['intersection_id'] != self.id:
                print(f"[{self.id}] Broadcast received: {msg}")
                self.handler(msg)

def run_intersection(intersection_id): #main program to simulate
    deletions(intersection_id) #remove this line later
    tl = OfflineTrafficLight(intersection_id)
    tl.load_state()

    def merge_log(incoming_entry): #for merging log entries that are concurrent, 
        #only one intersection will transmit at a time, will "wait" for each other
        sender = incoming_entry['intersection_id']
        if tl.frontiers.get(sender) == incoming_entry['id']:
            return

        if incoming_entry['reason'] == 'side_green' and tl.current_session_id:
            #Conflict detection for two concurrent sessions
            current_entry = tl.log[-1] if tl.log else None
            if current_entry and current_entry['reason'] == 'side_green':
                incoming_time = incoming_entry.get('timestamp')
                current_time = current_entry.get('timestamp')

                #compares timestamps, might not be very accurate in real uses (no global time), 
                #but LoRa is also unreliable like UDP so minor message inconsistency is expected
                if incoming_time and current_time and incoming_time < current_time:
                    print(f"[{tl.intersection_id}] Conflict: incoming session is earlier. Aborting my session.")
                    tl.current_session_id = None
                    tl.switch_back_time = None
                else:
                    print(f"[{tl.intersection_id}] Conflict: keeping my session (mine is earlier)")
                    return  #Do not merge

        tl.append_entry(incoming_entry)
        print(f"[{tl.intersection_id}] Merged log entry from {incoming_entry['intersection_id']}")


    def handle_message(msg):
        if msg['reason'] == 'side_green': #switch to green for the side when someone else switches to side
            tl.last_session_time = time.time()
            if tl.current_session_id != msg['id']:
                print(f"[{intersection_id}] Following side_green from {msg['intersection_id']}")
                tl.current_session_id = msg['id']
                tl.append_entry(msg)
                tl.state = msg['state']
                tl.switch_back_time = time.time() + SIDE_GREEN_DURATION
                tl.last_received_time = time.time()
        elif msg['reason'] == 'main_green': #others go back to main street we also go back to main street
            if tl.current_session_id == msg['id']:
                print(f"[{intersection_id}] Returning to main green by {msg['intersection_id']}")
                tl.append_entry(msg)
                tl.state = msg['state']
                tl.current_session_id = None
                tl.switch_back_time = None
                tl.last_received_time = time.time()


    comm = UDPCommunicator(intersection_id, handle_message) #udp communication later change
    listener_thread = threading.Thread(target=comm.receive, daemon=True)
    listener_thread.start()

    while True:
        now = time.time() #here with time - maybe change because "no global time"?

	#only start own sessions when no one else is doing anything- das sollte wahrscheinlich noch geändert werden, dass wir immer etwas machen, dann ist merge aber wieder schwieriger? So ist es ja fast wie bei Client-Server
        if (tl.current_session_id is None and (now - tl.last_session_time > tl.my_turn_timeout) and (now - tl.last_received_time > 3)):
            print(f"[{intersection_id}] Initiating local side green")
            session_id = str(uuid.uuid4())
            entry = {
                'id': session_id,
                'intersection_id': intersection_id,
                'state': {'main': 'RED', 'side': 'GREEN'},
                'reason': 'side_green',
                'timestamp': current_timestamp() #add timestamp for conflict free implementation
            }
            tl.append_entry(entry)
            tl.current_session_id = session_id
            tl.last_session_time = now
            tl.switch_back_time = now + SIDE_GREEN_DURATION
            comm.send(entry)

        if tl.current_session_id and tl.switch_back_time and now >= tl.switch_back_time:
            back = {
                'id': tl.current_session_id,
                'intersection_id': intersection_id,
                'state': {'main': 'GREEN', 'side': 'RED'},
                'reason': 'main_green'
            }
            print(f"[{intersection_id}] Switching back to main green")
            tl.append_entry(back)
            comm.send(back)
            tl.current_session_id = None
            tl.switch_back_time = None

        time.sleep(0.1)

#simulates randomly which intersections would be transmitting data
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python ampelnetz.py <intersection_id>")
        sys.exit(1)
    run_intersection(sys.argv[1])
