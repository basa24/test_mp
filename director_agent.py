"""
Horror Director Agent
Watches CV signals, tracks fear/engagement/tension, sends commands to Unity
"""
import asyncio
import websockets
import json
import time
from collections import deque
from threading import Thread

# --- CONFIG ---
CV_MODULE_URI = "ws://localhost:8765"  # Your CV module
UNITY_SERVER_PORT = 8766  # Unity connects here to receive commands
UPDATE_RATE = 0.5  # Send decisions to Unity every 0.5 seconds

# --- METRICS STATE ---
class HorrorDirector:
    def __init__(self):
        # Core metrics (0.0 - 1.0)
        self.fear = 0.5
        self.engagement = 0.5
        self.tension = 0.5
        
        # History tracking
        self.fear_history = deque(maxlen=300)  # 30 seconds at 10 Hz
        self.engagement_history = deque(maxlen=100)  # 10 seconds
        
        # Event tracking
        self.last_scare_time = 0
        self.last_attention_grab_time = 0
        self.last_relief_time = 0
        self.total_scares_triggered = 0
        
        # Tuning parameters
        self.MIN_SCARE_INTERVAL = 30.0  # Minimum seconds between jumpscares
        self.MIN_ATTENTION_GRAB_INTERVAL = 15.0
        self.FEAR_DECAY_RATE = 0.01  # How fast fear naturally drops
        self.TENSION_SMOOTHING = 0.9  # Higher = tension changes slower
        
        # State
        self.cv_connected = False
        self.last_cv_update = 0
        self.baseline_established = False
    
    def update(self, cv_signals):
        """Process new CV signals and update metrics"""
        current_time = time.time()
        self.last_cv_update = current_time
        
        # Check if baseline calibration done
        self.baseline_established = cv_signals.get("baselineEstablished", False)
        
        # --- UPDATE ENGAGEMENT ---
        # Direct from CV module's attentionScore
        raw_engagement = cv_signals.get("attentionScore", 0.5)
        self.engagement_history.append(raw_engagement)
        self.engagement = sum(self.engagement_history) / len(self.engagement_history)
        
        # --- UPDATE FEAR ---
        fear_delta = 0
        
        # Only use baseline-dependent signals if calibration done
        if self.baseline_established:
            blink_dev = cv_signals.get("blinkRateDeviation", 0)
            if blink_dev > 0.5:
                fear_delta += 0.05  # Blinking much more than normal
            elif blink_dev > 0.8:
                fear_delta += 0.08  # Very high blink rate
            elif blink_dev < -0.3:
                fear_delta += 0.03  # Frozen/focused (also fear signal)
        
        # Signals that work without calibration
        if cv_signals.get("lookingAway"):
            fear_delta += 0.04  # Avoidance behavior
        
        proximity = cv_signals.get("proximityState", "normal")
        if proximity == "far":
            fear_delta += 0.03  # Leaning back = retreat
        elif proximity == "close":
            fear_delta -= 0.01  # Leaning in = curiosity (less fear)
        
        if cv_signals.get("mouthOpen"):
            fear_delta += 0.12  # Gasping = strong fear signal
        
        if cv_signals.get("isSmiling"):
            fear_delta -= 0.06  # Not taking it seriously
        
        if not cv_signals.get("faceVisible"):
            fear_delta += 0.02  # Face gone = avoidance
        
        # Natural decay
        fear_delta -= self.FEAR_DECAY_RATE
        
        # Apply delta with bounds
        self.fear = max(0.0, min(1.0, self.fear + fear_delta))
        self.fear_history.append(self.fear)
        
        # --- UPDATE TENSION ---
        # Slow-moving average of fear (exponential moving average)
        if len(self.fear_history) > 0:
            recent_fear_avg = sum(list(self.fear_history)[-60:]) / min(60, len(self.fear_history))
            self.tension = (self.TENSION_SMOOTHING * self.tension + 
                          (1 - self.TENSION_SMOOTHING) * recent_fear_avg)
        
        self.tension = max(0.0, min(1.0, self.tension))
    
    def make_decision(self):
        """Decide what action to take based on current metrics"""
        current_time = time.time()
        
        # Time since last events
        time_since_scare = current_time - self.last_scare_time
        time_since_attention_grab = current_time - self.last_attention_grab_time
        time_since_relief = current_time - self.last_relief_time
        
        # Don't make decisions during calibration
        if not self.baseline_established:
            return {
                "action": "calibrating",
                "message": "Waiting for baseline calibration",
                "metrics": self.get_metrics()
            }
        
        # --- DECISION MATRIX ---
        
        # 1. ATTENTION GRAB (player disengaged)
        if (self.engagement < 0.4 and 
            time_since_attention_grab > self.MIN_ATTENTION_GRAB_INTERVAL):
            self.last_attention_grab_time = current_time
            return {
                "action": "attention_grab",
                "type": "ambient_sound" if self.tension < 0.5 else "visual_cue",
                "intensity": 0.4,
                "reason": f"Low engagement ({self.engagement:.2f})",
                "metrics": self.get_metrics()
            }
        
        # 2. RELIEF (tension too high, player needs break)
        if (self.tension > 0.75 and 
            time_since_relief > 45.0):
            self.last_relief_time = current_time
            return {
                "action": "relief",
                "duration_seconds": 10,
                "reason": f"High tension ({self.tension:.2f}), prevent burnout",
                "metrics": self.get_metrics()
            }
        
        # 3. JUMPSCARE (perfect window)
        if (self.fear < 0.4 and 
            self.engagement > 0.7 and 
            self.tension < 0.6 and
            time_since_scare > self.MIN_SCARE_INTERVAL):
            
            self.last_scare_time = current_time
            self.total_scares_triggered += 1
            
            # Intensity based on tension (higher tension = gentler scare)
            scare_intensity = 0.9 - (self.tension * 0.3)
            
            return {
                "action": "jumpscare",
                "intensity": round(scare_intensity, 2),
                "reason": f"Optimal window: low fear ({self.fear:.2f}), high engagement ({self.engagement:.2f}), manageable tension ({self.tension:.2f})",
                "metrics": self.get_metrics()
            }
        
        # 4. PAUSE (player overwhelmed, looking away)
        if self.engagement < 0.3 and self.fear > 0.6:
            return {
                "action": "pause",
                "reason": f"Player overwhelmed: high fear ({self.fear:.2f}), low engagement ({self.engagement:.2f})",
                "suggestion": "Let silence work, don't waste scares they won't see",
                "metrics": self.get_metrics()
            }
        
        # 5. ESCALATE (player engaged, moderately tense)
        if (self.engagement > 0.6 and 
            0.3 < self.tension < 0.7 and
            self.fear < 0.6):
            return {
                "action": "escalate",
                "ambient_intensity": round(self.tension + 0.2, 2),
                "music_tempo": round(1.0 + (self.tension * 0.5), 2),
                "reason": "Player engaged and handling tension well",
                "metrics": self.get_metrics()
            }
        
        # 6. CLIMAX (peak horror moment)
        if (self.fear > 0.7 and 
            self.engagement > 0.75 and 
            self.tension > 0.7):
            return {
                "action": "climax",
                "intensity": 1.0,
                "reason": "Peak horror: high fear, high engagement, high tension",
                "suggestion": "Big reveal or final scare, then RELIEF",
                "metrics": self.get_metrics()
            }
        
        # 7. SUSTAIN (default - keep current state)
        return {
            "action": "sustain",
            "ambient_intensity": round(self.tension, 2),
            "music_volume": round(0.3 + (self.tension * 0.4), 2),
            "reason": "Maintaining current tension level",
            "metrics": self.get_metrics()
        }
    
    def get_metrics(self):
        """Return current metric values"""
        return {
            "fear": round(self.fear, 2),
            "engagement": round(self.engagement, 2),
            "tension": round(self.tension, 2),
            "baseline_established": self.baseline_established,
            "total_scares": self.total_scares_triggered
        }
    
    def get_status(self):
        """Get full status for dashboard"""
        return {
            "metrics": self.get_metrics(),
            "cv_connected": self.cv_connected,
            "last_cv_update": self.last_cv_update,
            "history": {
                "fear": list(self.fear_history)[-30:],  # Last 3 seconds
                "engagement": list(self.engagement_history)[-30:]
            }
        }

# --- GLOBAL DIRECTOR INSTANCE ---
director = HorrorDirector()

# --- CV MODULE CLIENT (listens to your CV signals) ---
async def cv_module_client():
    """Connect to CV module and process signals"""
    print(f"🔌 Connecting to CV module at {CV_MODULE_URI}...")
    
    while True:
        try:
            async with websockets.connect(CV_MODULE_URI) as websocket:
                director.cv_connected = True
                print("✅ Connected to CV module")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        
                        # Skip status messages
                        if "status" in data:
                            continue
                        
                        # Update director with new CV signals
                        director.update(data)
                        
                    except json.JSONDecodeError:
                        print(f"⚠️ Invalid JSON from CV module: {message[:100]}")
        
        except Exception as e:
            director.cv_connected = False
            print(f"❌ CV module connection lost: {e}")
            print("🔄 Reconnecting in 2 seconds...")
            await asyncio.sleep(2)

# --- UNITY SERVER (Unity connects here to receive commands) ---
unity_clients = set()

async def unity_handler(websocket):
    """Handle Unity client connections"""
    unity_clients.add(websocket)
    print(f"🎮 Unity client connected. Total clients: {len(unity_clients)}")
    
    try:
        await websocket.send(json.dumps({"status": "connected", "message": "Director ready"}))
        
        # Keep connection alive, listen for any commands from Unity
        async for message in websocket:
            try:
                cmd = json.loads(message)
                print(f"📨 Unity command: {cmd}")
                # Could handle Unity -> Director commands here if needed
            except json.JSONDecodeError:
                pass
    
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        unity_clients.remove(websocket)
        print(f"🎮 Unity client disconnected. Total clients: {len(unity_clients)}")

async def broadcast_decisions():
    """Send decisions to Unity clients periodically"""
    while True:
        await asyncio.sleep(UPDATE_RATE)
        
        if unity_clients:
            decision = director.make_decision()
            message = json.dumps(decision)
            
            # Broadcast to all Unity clients
            await asyncio.gather(
                *[client.send(message) for client in unity_clients],
                return_exceptions=True
            )

async def unity_server():
    """WebSocket server for Unity to connect to"""
    async with websockets.serve(unity_handler, "localhost", UNITY_SERVER_PORT):
        print(f"🚀 Unity server started on ws://localhost:{UNITY_SERVER_PORT}")
        await broadcast_decisions()

# --- CONSOLE STATUS DISPLAY ---
def print_status_loop():
    """Print director status to console periodically"""
    while True:
        time.sleep(2)
        
        status = director.get_status()
        metrics = status["metrics"]
        
        # Clear screen (optional, comment out if annoying)
        # print("\033[2J\033[H", end="")
        
        print("\n" + "="*60)
        print("🎬 HORROR DIRECTOR STATUS")
        print("="*60)
        print(f"CV Connected: {'✅' if status['cv_connected'] else '❌'}")
        print(f"Unity Clients: {len(unity_clients)}")
        print(f"Baseline: {'✅' if metrics['baseline_established'] else '⏳ Calibrating...'}")
        print()
        print(f"😱 FEAR:       {metrics['fear']:.2f} {'█' * int(metrics['fear'] * 20)}")
        print(f"👁️  ENGAGEMENT: {metrics['engagement']:.2f} {'█' * int(metrics['engagement'] * 20)}")
        print(f"⚡ TENSION:    {metrics['tension']:.2f} {'█' * int(metrics['tension'] * 20)}")
        print()
        print(f"Total Scares Triggered: {metrics['total_scares']}")
        print("="*60)

# --- MAIN ---
async def main():
    # Start status printer in background thread
    Thread(target=print_status_loop, daemon=True).start()
    
    print("""
╔══════════════════════════════════════════════════════════╗
║           🎬 HORROR DIRECTOR AGENT v1.0                 ║
╚══════════════════════════════════════════════════════════╝

Architecture:
  CV Module (port 8765) → Director Agent → Unity (port 8766)

Metrics tracked:
  😱 Fear:       Immediate fear response (0-1)
  👁️  Engagement: Attention to screen (0-1)  
  ⚡ Tension:    Sustained stress over time (0-1)

Starting services...
""")
    
    # Run both CV client and Unity server concurrently
    await asyncio.gather(
        cv_module_client(),
        unity_server()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Director shutting down...")