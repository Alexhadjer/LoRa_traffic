import threading 
import time
import json
import os
import shutil
import utils
import uuid
from datetime import datetime

intersection, port, host, interval, temp = utils.cli()
frontier = {}
frontier_dir = f"frontiers/{intersection}"
switch_interval = 12 #time between light changes, can be changed

overload_factor = 0.5 #additional time for traffic overlaod, can be changed
overload_active = False #set to false in the beginning
overload_road = None
overload_ends_at = 0

emergency_active = False
emergency_ends_at = 0

sock = utils.setup_socket("", port) 

def current_timestamp(): #for creating timestamp for the log file
    return datetime.now().isoformat() + ' '

def delete_files(): #only for testing to start with clean environment each time
    if os.path.exists(frontier_dir):
        try:
            shutil.rmtree(frontier_dir) #deleting the frontier files
        except Exception as e:
            print("Could not delete files: ", e)
            
delete_files() #remove this line for serious use

def run_intersections():
    global last_merge_time, overload_active, overload_road, overload_ends_at, emergency_active, emergency_ends_at #to save when we merged last
    while True:
        time.sleep(0.1) #check very often
        
        if emergency_active and time.time() >= emergency_ends_at: # Check if emergency has ended
            print(f"[{intersection}] Emergency ended. Resuming normal operation.")
            emergency_active = False
            switch_light()

        if emergency_active:
            continue

        #check if overload expired
        if overload_active:
            if time.time() >= overload_ends_at:
                print(f"[{intersection}] Overload period ended. Resuming normal operation.")
                overload_active = False
                overload_road = None
                overload_ends_at = 0
                frontier[intersection] += 1
                switch_light()

            else:
            #while in overload, keep printing the state every few seconds
                if int(time.time() * 10) % 10 == 0:  # every 1s approx
                    switch_light()
                continue  #don't run CRDT switching

        if time.time() - last_merge_time >= switch_interval: #after every switch-interval switch the traffic lights
            if can_switch():
                frontier[intersection] += 1
                switch_light()

def switch_light(): #to change which street has green lights
    global last_merge_time, overload_active, overload_road, emergency_active
    
    if emergency_active:
        print(f"[{intersection}] Switching to emergency: All lights RED")
        last_merge_time = time.time()
        return
        
    if overload_active:
        if overload_road == "M": #TODO: does not print out like its supposed to but close?
            print(f"[{intersection}] Traffic overload: Holding MAIN ROAD green")
        else:
            print(f"[{intersection}] Traffic overload: Holding SIDE ROAD green")
        if not temp:
            save_frontier() #update our frontier files
        last_merge_time = time.time() #set timestamp back
    else:
        if frontier [intersection] % 2 == 0: #even numbers are for the main road
            print(f"[{intersection}] Switching to MAIN ROAD green")
        else: #odd numbers for the side road
            print(f"[{intersection}] Switching to SIDE ROAD green")
        if not temp:
            save_frontier() #update our frontier files
        last_merge_time = time.time() #set timestamp back

def can_switch():
    my_frontier = frontier.get(intersection, 0)
    return all(count == my_frontier for count in frontier.values()) #only switch when everyone is at the same step

def send():
    while True:
        if not overload_active: #only send when not in overload
            message = json.dumps(frontier).encode("utf-8") #convert into JSON
            sock.sendto(message, (host, port)) #change this to LoRa
        time.sleep(interval) #broadcast every interval

def load_frontier():
    frontier[intersection] = 0
    if temp: #when creating a temp peer he didn't store
        return
    os.makedirs(frontier_dir, exist_ok=True) #do nothing if it already exists
    for filename in os.listdir(frontier_dir):
        path = os.path.join(frontier_dir, filename) #here create the full paths
        try:
            with open(path, "r") as file:
                count = int(file.read().strip()) #read count
                name = filename.replace(".txt", "") #remove the .txt to get name 
                frontier[name] = count
        except Exception:
            continue
        
def save_frontier():
    for user in frontier:
        try:
            with open(f"{frontier_dir}/{user}.txt", 'w') as file: #w for write
                file.write(str(frontier[user])) #write into file
        except Exception as e:
            print(f"Error: {e}")

def append_entry(entry): #append to log file and update frontier
    log_file = f"log_{intersection}.txt"
    with open(log_file, 'a') as f:
        f.write(json.dumps(entry) + "\n")
    frontier[entry['intersection_id']] = frontier.get(entry['intersection_id'], 0)
    if not temp:
        save_frontier()

def receive():
    global overload_active, overload_road, emergency_active, emergency_ends_at
    while True:
        data, addr = sock.recvfrom(1024) #change this to LoRa
        try:
            received = json.loads(data.decode("utf-8"))
            if isinstance(received, dict):
            	if received.get("reason") == "emergency":
                    append_entry(received)
                    emergency_active = True
                    emergency_ends_at = time.time() + 15
                    switch_light()
                    continue
            
            	if "reason" in received and received["reason"].startswith("overload"):
                    overload_road = "M" if "M" in received["reason"] else "S"
                    append_entry(received)
                    activate_overload(overload_road)
            if overload_active or emergency_active:
                continue #skip normal message processing if overload is active

            updated = False
            for user in received:
                count = received[user]
                if user not in frontier or frontier[user] < count:
                    frontier[user] = count #merge
                    updated = True
            if updated:
                my_value = frontier.get(intersection, 0)
                max_other = max((v for k, v in frontier.items() if k != intersection), default=my_value)
                if max_other > my_value:
                    frontier[intersection] = max_other #catch up
                    switch_light() #after merge show the light changes
            display()
        except Exception as e:
            print("Error:", e)     

def display(): #displaying traffic info
    states = []
    for user in sorted(frontier):
        state = "SIDE GREEN"
        if frontier[user] % 2 == 0:
            state = "MAIN GREEN"
        states.append(f"{user}: {state} ({frontier[user]})")
    print("Traffic states -", ", ".join(states))

def overload_input(): #for simulating the overflow of traffic
    global overload_active, overload_road, overload_ends_at, emergency_active, emergency_ends_at
    while True:
        user_input = input().strip()
        if user_input == "M" or user_input == "S":
            overload_entry = { #for writing the overload into the log files
                "id": str(uuid.uuid4()),
                "intersection_id": intersection,
                "state": {"main": "GREEN", "side": "RED"} if user_input == "M" else {"main": "RED", "side": "GREEN"},
                "reason": f"overload_{user_input}",
                "timestamp": current_timestamp()
            }
            append_entry(overload_entry)
            sock.sendto(json.dumps(overload_entry).encode("utf-8"), (host, port))
            road_name = "MAIN" if user_input == "M" else "SIDE"
            print(f"[{intersection}] Overload active: Holding {road_name} ROAD green for {switch_interval * overload_factor} s")
            activate_overload(user_input)
        elif user_input == "E":
            emergency_entry = {
                "id": str(uuid.uuid4()),
                "intersection_id": intersection,
                "state": {"main": "RED", "side": "RED"},
                "reason": "emergency",
                "timestamp": current_timestamp() 
            }
            append_entry(emergency_entry)
            sock.sendto(json.dumps(emergency_entry).encode("utf-8"), (host, port))
            print(f"[{intersection}] Emergency activated: All lights RED for 15s")
            emergency_active = True
            emergency_ends_at = time.time() + 15
            switch_light()
                
def activate_overload(road):
    global overload_active, overload_road, overload_ends_at
    overload_active = True
    overload_ends_at = time.time() + switch_interval * overload_factor
    switch_light()

load_frontier() #load what we saved
last_merge_time = time.time()
print("Enter M for traffic overload on main road, S on side road. Enter E for emergency.")
print(f"[{intersection}] MAIN ROAD green")
threading.Thread(target=send, daemon=True).start()
threading.Thread(target=receive, daemon=True).start()
threading.Thread(target=overload_input, daemon=True).start()
try:
    run_intersections()
except KeyboardInterrupt:
    print(f"End intersection")
    exit(0)
