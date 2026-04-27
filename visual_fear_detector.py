"""
Visual Fear Detector using Ollama Vision Models
Directly analyzes webcam frames to detect fear/emotions
"""
import cv2
import time
import json
import ollama
import asyncio
import websockets
from threading import Thread, Lock
from collections import deque
import base64

# --- CONFIG ---
OLLAMA_VISION_MODEL = "moondream"  # or "bakllava", "llava-phi", "moondream" if you have them
ANALYSIS_INTERVAL = 3.0  # Analyze every 3 seconds (vision models are slow)
WEBSOCKET_PORT = 8766

# --- STATE ---
latest_analysis = {
    "timestamp": 0,
    "fear_level": 0.0,
    "emotion": "neutral",
    "facial_cues": [],
    "confidence": 0.0,
    "reasoning": ""
}
analysis_lock = Lock()
connected_clients = set()

def encode_frame_to_base64(frame):
    """Convert OpenCV frame to base64 for Ollama"""
    # Resize for faster processing
    small_frame = cv2.resize(frame, (512, 512))
    _, buffer = cv2.imencode('.jpg', small_frame)
    return base64.b64encode(buffer).tobytes()

def analyze_fear_with_ollama(frame):
    """Use Ollama vision model to analyze fear from facial expression"""
    global latest_analysis
    
    try:
        print(f"🤖 Analyzing facial expression with {OLLAMA_VISION_MODEL}...")
        start_time = time.time()
        
        # Encode frame
        image_bytes = encode_frame_to_base64(frame)
        
        # Prompt for fear analysis
        prompt = """Analyze this person's facial expression and determine their fear level.

Look for these fear indicators:
- Wide eyes or raised eyebrows (surprise/fear)
- Tense jaw or clenched teeth (anxiety)
- Open mouth (gasp/shock)
- Pale skin or sweat (stress)
- Looking away or avoiding camera (avoidance)
- Furrowed brow (worry/concern)

Rate the person's fear level from 0.0 (completely calm) to 1.0 (terrified).

Respond ONLY with valid JSON (no markdown):
{
  "fear_level": 0.0 to 1.0,
  "emotion": "calm" | "neutral" | "anxious" | "scared" | "terrified" | "other",
  "facial_cues": ["list", "of", "observed", "cues"],
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation"
}"""

        # Call Ollama vision model
        response = ollama.generate(
            model=OLLAMA_VISION_MODEL,
            prompt=prompt,
            images=[image_bytes],
            stream=False
        )
        
        inference_time = time.time() - start_time
        print(f"✅ Analysis complete in {inference_time:.1f}s")
        
        # Parse response
        raw_text = response['response'].strip()
        
        # Extract JSON
        if "```json" in raw_text:
            json_start = raw_text.find("```json") + 7
            json_end = raw_text.find("```", json_start)
            raw_text = raw_text[json_start:json_end].strip()
        elif "```" in raw_text:
            json_start = raw_text.find("```") + 3
            json_end = raw_text.find("```", json_start)
            raw_text = raw_text[json_start:json_end].strip()
        elif "{" in raw_text and "}" in raw_text:
            # Find first { and last }
            json_start = raw_text.find("{")
            json_end = raw_text.rfind("}") + 1
            raw_text = raw_text[json_start:json_end]
        
        try:
            result = json.loads(raw_text)
        except:
            print(f"⚠️ Failed to parse JSON, raw: {raw_text[:200]}")
            # Fallback - try to extract fear level from text
            if "fear" in raw_text.lower():
                # Simple heuristic
                if "terrified" in raw_text.lower() or "very scared" in raw_text.lower():
                    fear_level = 0.8
                elif "scared" in raw_text.lower() or "afraid" in raw_text.lower():
                    fear_level = 0.6
                elif "anxious" in raw_text.lower() or "nervous" in raw_text.lower():
                    fear_level = 0.4
                else:
                    fear_level = 0.2
            else:
                fear_level = 0.1
            
            result = {
                "fear_level": fear_level,
                "emotion": "uncertain",
                "facial_cues": ["unable to parse detailed response"],
                "confidence": 0.3,
                "reasoning": raw_text[:100]
            }
        
        # Update global state
        with analysis_lock:
            latest_analysis = {
                "timestamp": time.time(),
                "fear_level": result.get("fear_level", 0.0),
                "emotion": result.get("emotion", "unknown"),
                "facial_cues": result.get("facial_cues", []),
                "confidence": result.get("confidence", 0.0),
                "reasoning": result.get("reasoning", ""),
                "inference_time": inference_time,
                "model": OLLAMA_VISION_MODEL
            }
        
        print(f"😱 Fear Level: {latest_analysis['fear_level']:.2f} | Emotion: {latest_analysis['emotion']}")
        
        return latest_analysis
        
    except Exception as e:
        print(f"❌ Analysis error: {e}")
        return None

def webcam_analysis_loop():
    """Capture frames and analyze periodically"""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Could not open webcam")
        return
    
    print("📹 Webcam opened, starting analysis loop")
    
    # Warm up
    for _ in range(5):
        cap.read()
    
    last_analysis_time = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        current_time = time.time()
        
        # Analyze periodically
        if current_time - last_analysis_time >= ANALYSIS_INTERVAL:
            last_analysis_time = current_time
            
            # Run analysis in main thread (blocking)
            analyze_fear_with_ollama(frame.copy())
        
        # Show webcam (optional)
        # cv2.imshow("Fear Detector", frame)
        
        time.sleep(0.1)
        
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
    
    cap.release()
    # cv2.destroyAllWindows()

# --- WEBSOCKET SERVER ---
async def websocket_handler(websocket):
    """Handle client connections"""
    connected_clients.add(websocket)
    print(f"🔌 Client connected. Total: {len(connected_clients)}")
    
    try:
        await websocket.send(json.dumps({
            "status": "connected",
            "message": "Visual Fear Detector ready"
        }))
        
        # Send initial state
        with analysis_lock:
            await websocket.send(json.dumps(latest_analysis))
        
        # Listen for commands
        async for message in websocket:
            try:
                cmd = json.loads(message)
                print(f"📨 Command: {cmd}")
                
                if cmd.get("command") == "get_analysis":
                    with analysis_lock:
                        await websocket.send(json.dumps(latest_analysis))
                
                elif cmd.get("command") == "ping":
                    await websocket.send(json.dumps({"status": "ok", "message": "pong"}))
            
            except json.JSONDecodeError:
                pass
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)
        print(f"🔌 Client disconnected")

async def broadcast_loop():
    """Broadcast updates when new analysis available"""
    last_broadcast_timestamp = 0
    
    while True:
        await asyncio.sleep(1)
        
        with analysis_lock:
            if latest_analysis["timestamp"] > last_broadcast_timestamp and connected_clients:
                last_broadcast_timestamp = latest_analysis["timestamp"]
                message = json.dumps(latest_analysis)
                
                await asyncio.gather(
                    *[client.send(message) for client in connected_clients],
                    return_exceptions=True
                )

async def websocket_server():
    """Start WebSocket server"""
    async with websockets.serve(websocket_handler, "localhost", WEBSOCKET_PORT):
        print(f"🚀 WebSocket server on ws://localhost:{WEBSOCKET_PORT}")
        await broadcast_loop()

def run_websocket_server():
    """Run WebSocket in separate thread"""
    asyncio.run(websocket_server())

# --- STATUS DISPLAY ---
def print_status_loop():
    """Print current analysis to console"""
    while True:
        time.sleep(5)
        
        with analysis_lock:
            analysis = latest_analysis.copy()
        
        if analysis["timestamp"] == 0:
            continue
        
        age = time.time() - analysis["timestamp"]
        
        print("\n" + "="*70)
        print("👁️  VISUAL FEAR DETECTOR STATUS")
        print("="*70)
        print(f"Model: {analysis.get('model', 'unknown')}")
        print(f"Last Analysis: {age:.1f}s ago")
        print()
        print(f"😱 FEAR LEVEL: {analysis['fear_level']:.2f} {'█' * int(analysis['fear_level'] * 30)}")
        print(f"😐 EMOTION:    {analysis['emotion']}")
        print(f"✅ CONFIDENCE: {analysis['confidence']:.2f}")
        print()
        if analysis['facial_cues']:
            print("Observed cues:")
            for cue in analysis['facial_cues']:
                print(f"  • {cue}")
        print()
        print(f"Reasoning: {analysis['reasoning']}")
        print("="*70)

# --- MAIN ---
def main():
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║        👁️  VISUAL FEAR DETECTOR (Ollama Vision)             ║
╚══════════════════════════════════════════════════════════════╝

Uses: {OLLAMA_VISION_MODEL}
Analysis Interval: Every {ANALYSIS_INTERVAL}s

This system:
1. Captures webcam frames
2. Sends to Ollama vision model
3. Gets fear level + emotion analysis
4. Broadcasts results via WebSocket

No hand-crafted rules - pure AI vision analysis!

Starting...
""")
    
    # Check if model exists
    try:
        models = ollama.list()
        model_names = [m['name'] for m in models.get('models', [])]
        if not any(OLLAMA_VISION_MODEL in name for name in model_names):
            print(f"⚠️  WARNING: {OLLAMA_VISION_MODEL} not found!")
            print(f"Available models: {model_names}")
            print(f"\nTo install: ollama pull {OLLAMA_VISION_MODEL}")
            return
    except:
        pass
    
    # Start background threads
    ws_thread = Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()
    
    status_thread = Thread(target=print_status_loop, daemon=True)
    status_thread.start()
    
    time.sleep(1)
    
    # Run webcam analysis in main thread
    try:
        webcam_analysis_loop()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")

if __name__ == "__main__":
    main()