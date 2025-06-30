import threading
import time
import json
import os
import utils
import shutil

intersection, port, host, interval, temp = utils.cli()
frontier = {}
frontier_dir = f"frontiers/{intersection}"
switch_interval = 12 #time between light changes, can be changed

sock = utils.setup_socket("", port) 

def delete_files(): #only for testing to start with clean environment each time
    if os.path.exists(frontier_dir):
    	try:
    	    shutil.rmtree(frontier_dir) #deleting the frontier files
    	except Exception as e:
    	    print(" ")
    	    
delete_files() #remove this line for serious use

def run_intersections():
    global last_merge_time #to save when we merged last
    while True:
        time.sleep(0.1) #check very often
        if time.time() - last_merge_time >= switch_interval: #after every switch-interval switch the traffic lights
            if can_switch():
                frontier[intersection] += 1
                switch_light()

def switch_light(): #to change which street has green lights
    global last_merge_time
    if frontier [intersection] % 2 == 0: #even numbers are for the main road
    	print(f"[{intersection}] Switching to MAIN ROAD green")
    else: #odd numbers for the side road
    	print(f"[{intersection}] Switching to SIDE ROAD green")
    if not temp:
    	save_frontier() #update our frontier files
    last_merge_time = time.time() #set timestamp back

def can_switch():
    my_frontier = frontier.get(intersection, 0)
    return all(count == my_frontier for count in frontier.values()) #only switch when everyone is at the same step

def send():
    while True:
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

def receive():
    global last_merge_time
    while True:
        data, addr = sock.recvfrom(1024) #change this to LoRa
        try:
            received = json.loads(data.decode("utf-8"))
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

def display():
    states = []
    for user in sorted(frontier):
    	state = "SIDE GREEN"
    	if frontier[user] % 2 == 0:
    	    state = "MAIN GREEN"
    	states.append(f"{user}: {state} ({frontier[user]})")
    print("Traffic states -", ", ".join(states))

load_frontier() #load what we saved
last_merge_time = time.time()
print(f"[{intersection}] MAIN ROAD green")
threading.Thread(target=send, daemon=True).start()
threading.Thread(target=receive, daemon=True).start()
run_intersections() 
