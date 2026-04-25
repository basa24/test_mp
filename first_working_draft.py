import cv2
import time
import json
import math
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import os

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
CALIBRATION_DURATION = 20.0  # seconds
calibration_start_time = time.time()
baseline_established = False
baseline_blinks_per_min = 0.0

# Blink tracking
blink_times = []  # timestamps of detected blinks
last_blink_state = False  # for edge detection

while True:
    success, frame = cap.read()
    if not success:
        break

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    frame_timestamp_ms += 33
    result = detector.detect_for_video(mp_image, frame_timestamp_ms)

    current_time = time.time()
    elapsed_time = current_time - calibration_start_time

    if result.face_landmarks:
        data = {
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
            
            # Blink detection with EDGE DETECTION (only count rising edge)
            current_blink_state = (
                data["leftBlinkScore"] > 0.5 and data["rightBlinkScore"] > 0.5
            )
            data["blinkDetected"] = current_blink_state
            
            # Rising edge = new blink started
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

        # --- BASELINE CALIBRATION LOGIC ---
        if not baseline_established:
            if elapsed_time >= CALIBRATION_DURATION:
                # Calibration period over - calculate baseline
                if len(blink_times) > 0:
                    baseline_blinks_per_min = (len(blink_times) / CALIBRATION_DURATION) * 60
                else:
                    baseline_blinks_per_min = 10.0  # default if no blinks detected
                
                baseline_established = True
                print(f"\n🎯 BASELINE ESTABLISHED: {baseline_blinks_per_min:.1f} blinks/min\n")
            
            data["baselineEstablished"] = False
            data["calibrationSecondsRemaining"] = round(CALIBRATION_DURATION - elapsed_time, 1)
        
        else:
            # Baseline established - calculate deviation
            # Count blinks in last 10 seconds
            recent_blinks = [t for t in blink_times if current_time - t <= 10.0]
            current_blinks_per_min = (len(recent_blinks) / 10.0) * 60
            
            # Calculate deviation
            if baseline_blinks_per_min > 0:
                deviation = (current_blinks_per_min - baseline_blinks_per_min) / baseline_blinks_per_min
            else:
                deviation = 0.0
            
            data["baselineEstablished"] = True
            data["baselineBlinksPerMin"] = round(baseline_blinks_per_min, 1)
            data["currentBlinksPerMin"] = round(current_blinks_per_min, 1)
            data["blinkRateDeviation"] = round(deviation, 2)

    else:
        data = {"faceVisible": False}

    print(json.dumps(data, indent=2))

    cv2.imshow("Webcam", frame)
    time.sleep(0.1)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()