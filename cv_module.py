import cv2
import time
import json
import math
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import os
import asyncio
import websockets
from threading import Thread

base_options = python.BaseOptions(
   model_asset_path=r"C:\Users\aksha\Downloads\face_landmarker.task"
)

options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    output_face_blendshapes=True,
    output_facial_transformation_matrixes=True,
    num_faces=1
)

detector = vision.FaceLandmarker.create_from_options(options)
cap = cv2.VideoCapture(0)

frame_timestamp_ms = 0

# --- BASELINE CALIBRATION STATE ---
CALIBRATION_DURATION = 20.0
calibration_start_time = time.time()
baseline_established = False
baseline_blinks_per_min = 0.0

blink_times = []
last_blink_state = False

# --- ATTENTION TRACKING ---
attention_history = []  # rolling window of attention samples
ATTENTION_WINDOW = 30  # track last 30 samples (~3 seconds at 10 Hz)
last_face_seen_time = time.time()

# --- WEBSOCKET STATE ---
connected_clients = set()
latest_data = {"faceVisible": False}
command_queue = []  # Commands received from clients

def reset_baseline():
    """Reset baseline calibration"""
    global calibration_start_time, baseline_established, baseline_blinks_per_min, blink_times
    calibration_start_time = time.time()
    baseline_established = False
    baseline_blinks_per_min = 0.0
    blink_times = []
    print("🔄 BASELINE RESET - Starting new calibration period")

async def websocket_handler(websocket):
    """Handle new WebSocket connections"""
    connected_clients.add(websocket)
    print(f"🔌 Client connected. Total clients: {len(connected_clients)}")
    
    try:
        # Send initial connection confirmation
        await websocket.send(json.dumps({"status": "connected", "message": "CV module ready"}))
        
        # Listen for commands from game
        async for message in websocket:
            try:
                cmd = json.loads(message)
                print(f"📨 Received command: {cmd}")
                
                # Handle different command types
                if cmd.get("command") == "resetBaseline":
                    command_queue.append(("resetBaseline", None))
                    await websocket.send(json.dumps({"status": "ok", "message": "Baseline reset initiated"}))
                
                elif cmd.get("command") == "ping":
                    await websocket.send(json.dumps({"status": "ok", "message": "pong"}))
                
                else:
                    await websocket.send(json.dumps({"status": "error", "message": f"Unknown command: {cmd.get('command')}"}))
            
            except json.JSONDecodeError:
                print(f"⚠️ Invalid JSON received: {message}")
                await websocket.send(json.dumps({"status": "error", "message": "Invalid JSON"}))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)
        print(f"🔌 Client disconnected. Total clients: {len(connected_clients)}")

async def broadcast_data():
    """Broadcast latest CV data to all connected clients"""
    while True:
        if connected_clients and latest_data:
            message = json.dumps(latest_data)
            await asyncio.gather(
                *[client.send(message) for client in connected_clients],
                return_exceptions=True
            )
        await asyncio.sleep(0.1)  # 10 Hz broadcast rate

async def websocket_server():
    """Start WebSocket server on port 8765"""
    async with websockets.serve(websocket_handler, "localhost", 8765):
        print("🚀 WebSocket server started on ws://localhost:8765")
        await broadcast_data()

def run_websocket_server():
    """Run WebSocket server in separate thread"""
    asyncio.run(websocket_server())

# Start WebSocket server in background thread
ws_thread = Thread(target=run_websocket_server, daemon=True)
ws_thread.start()

print("⏳ Starting CV pipeline... WebSocket server running in background.")
time.sleep(1)

# --- MAIN CV LOOP ---
while True:
    success, frame = cap.read()
    if not success:
        break

    # Process any pending commands
    while command_queue:
        cmd, args = command_queue.pop(0)
        if cmd == "resetBaseline":
            reset_baseline()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    frame_timestamp_ms += 33
    result = detector.detect_for_video(mp_image, frame_timestamp_ms)

    current_time = time.time()
    elapsed_time = current_time - calibration_start_time

    if result.face_landmarks:
        last_face_seen_time = current_time  # Update last seen time
        
        data = {
            "timestamp": current_time,
            "faceVisible": True,
            "numFaces": len(result.face_landmarks)
        }

        # --- BLENDSHAPES ---
        if result.face_blendshapes:
            scores = {
                item.category_name: item.score
                for item in result.face_blendshapes[0]
            }

            data["leftBlinkScore"] = scores.get("eyeBlinkLeft", 0)
            data["rightBlinkScore"] = scores.get("eyeBlinkRight", 0)
            data["smileLeft"] = scores.get("mouthSmileLeft", 0)
            data["smileRight"] = scores.get("mouthSmileRight", 0)
            data["jawOpen"] = scores.get("jawOpen", 0)
            
            current_blink_state = (
                data["leftBlinkScore"] > 0.5 and data["rightBlinkScore"] > 0.5
            )
            data["blinkDetected"] = current_blink_state
            
            if current_blink_state and not last_blink_state:
                blink_times.append(current_time)
            
            last_blink_state = current_blink_state
            
            data["isSmiling"] = (
                (data["smileLeft"] + data["smileRight"]) / 2 > 0.4
            )
            data["mouthOpen"] = data["jawOpen"] > 0.3

        # --- HEAD POSE ---
        if result.facial_transformation_matrixes:
            matrix = np.array(result.facial_transformation_matrixes[0]).reshape(4, 4)
            rotation_matrix = matrix[:3, :3]

            rot_vec, _ = cv2.Rodrigues(rotation_matrix)
            
            pitch = -rot_vec[0][0] * (180 / math.pi)
            yaw = rot_vec[1][0] * (180 / math.pi)
            
            data["headYawDegrees"] = round(float(yaw), 1)
            data["headPitchDegrees"] = round(float(pitch), 1)
            data["lookingAway"] = bool(abs(yaw) > 25 or abs(pitch) > 25)

        # --- BASELINE CALIBRATION ---
        if not baseline_established:
            if elapsed_time >= CALIBRATION_DURATION:
                if len(blink_times) > 0:
                    baseline_blinks_per_min = (len(blink_times) / CALIBRATION_DURATION) * 60
                else:
                    baseline_blinks_per_min = 10.0
                
                baseline_established = True
                print(f"\n🎯 BASELINE ESTABLISHED: {baseline_blinks_per_min:.1f} blinks/min\n")
            
            data["baselineEstablished"] = False
            data["calibrationSecondsRemaining"] = round(CALIBRATION_DURATION - elapsed_time, 1)
        
        else:
            recent_blinks = [t for t in blink_times if current_time - t <= 10.0]
            current_blinks_per_min = (len(recent_blinks) / 10.0) * 60
            
            if baseline_blinks_per_min > 0:
                deviation = (current_blinks_per_min - baseline_blinks_per_min) / baseline_blinks_per_min
            else:
                deviation = 0.0
            
            data["baselineEstablished"] = True
            data["baselineBlinksPerMin"] = round(baseline_blinks_per_min, 1)
            data["currentBlinksPerMin"] = round(current_blinks_per_min, 1)
            data["blinkRateDeviation"] = round(deviation, 2)

        # --- ATTENTION SCORE CALCULATION ---
        instant_attention = 1.0
        
        # Penalty for looking away
        if data.get("lookingAway", False):
            instant_attention *= 0.3
        
        # Penalty for excessive blinking (discomfort/avoidance)
        if baseline_established and data.get("blinkRateDeviation", 0) > 0.5:
            instant_attention *= 0.7
        
        # Penalty for looking away from screen for extended time
        time_since_looking = 0.0  # Face visible and looking = 0
        
        attention_history.append(instant_attention)

    else:
        # No face detected
        time_since_looking = current_time - last_face_seen_time
        
        # Attention drops quickly when face disappears
        instant_attention = max(0.0, 1.0 - (time_since_looking / 5.0))  # Drops to 0 over 5 seconds
        attention_history.append(instant_attention)
        
        data = {
            "timestamp": current_time,
            "faceVisible": False,
            "secondsSinceFaceVisible": round(time_since_looking, 1)
        }

    # Keep only last N samples for smoothing
    if len(attention_history) > ATTENTION_WINDOW:
        attention_history.pop(0)

    # Smoothed attention score
    if attention_history:
        data["attentionScore"] = round(sum(attention_history) / len(attention_history), 2)
    else:
        data["attentionScore"] = 0.0

    # Update shared state for WebSocket broadcast
    latest_data = data
    
    # Print to console for debugging
    print(json.dumps(data, indent=2))

    cv2.imshow("Webcam", frame)
    time.sleep(0.1)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()