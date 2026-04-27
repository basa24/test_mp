"""
Hybrid Horror Director Agent
Rules engine gates decisions + Ollama LLM makes creative choices
"""
import asyncio
import websockets
import json
import time
import ollama
from collections import deque
from threading import Thread

# --- CONFIG ---
CV_MODULE_URI = "ws://localhost:8765"
UNITY_SERVER_PORT = 8766
UPDATE_RATE = 1.0  # Check for decisions every second

# Ollama config
OLLAMA_MODEL = "llama3.2"  # Change to whatever you have installed
USE_OLLAMA = True  # Set to False to fall back to pure rules

# --- DIRECTOR STATE ---
class HybridDirector:
    def __init__(self):
        # Simplified to 2 core metrics
        self.fear_score = 0.5
        self.attention_score = 0.5
        
        # History for smoothing
        self.fear_history = deque(maxlen=100)  # 10 seconds at 10 Hz
        self.attention_history = deque(maxlen=100)
        
        # Event tracking
        self.last_scare_time = 0
        self.last_ai_decision_time = 0
        self.total_scares_triggered = 0
        self.total_ai_calls = 0
        self.ai_failures = 0
        
        # Cooldowns (hard constraints)
        self.MIN_SCARE_INTERVAL = 10.0  # Minimum 10s between jumpscares (DEMO MODE)  # Minimum 30s between jumpscares
        self.MIN_AI_CALL_INTERVAL = 5.0  # Don't spam Ollama
        
        # Player profile (builds over time)
        self.player_profile = {
            "avg_fear": 0.5,
            "peak_fear": 0.0,
            "smiles_during_scares": 0,
            "times_looked_away": 0
        }
        
        # State
        self.cv_connected = False
        self.last_cv_update = 0
        self.baseline_established = False
        self.last_decision = {"action": "waiting"}
    
    def update(self, cv_signals):
        """Process CV signals and update metrics"""
        current_time = time.time()
        self.last_cv_update = current_time
        self.baseline_established = cv_signals.get("baselineEstablished", False)
        
        # --- UPDATE ATTENTION SCORE ---
        # Direct from CV module
        raw_attention = cv_signals.get("attentionScore", 0.5)
        self.attention_history.append(raw_attention)
        self.attention_score = sum(self.attention_history) / len(self.attention_history)
        
        # --- UPDATE FEAR SCORE ---
        # Weighted combination of all "scared" signals
        fear_components = []
        
        # Only use baseline-dependent signals if calibrated
        if self.baseline_established:
            blink_dev = cv_signals.get("blinkRateDeviation", 0)
            # Normalize to 0-1 (deviation of ±1.0 maps to 0-1)
            blink_contribution = min(1.0, abs(blink_dev))
            fear_components.append(("blink_rate", blink_contribution, 0.3))  # 30% weight
        
        # Signals that work without calibration
        looking_away = 1.0 if cv_signals.get("lookingAway") else 0.0
        fear_components.append(("looking_away", looking_away, 0.2))  # 20% weight
        
        face_visible = 1.0 if cv_signals.get("faceVisible") else 0.0
        face_missing = 1.0 - face_visible
        fear_components.append(("face_missing", face_missing, 0.15))  # 15% weight
        
        mouth_open = 1.0 if cv_signals.get("mouthOpen") else 0.0
        fear_components.append(("mouth_open", mouth_open, 0.25))  # 25% weight (strong signal)
        
        proximity = cv_signals.get("proximityState", "normal")
        leaning_back = 1.0 if proximity == "far" else 0.0
        fear_components.append(("leaning_back", leaning_back, 0.1))  # 10% weight
        
        # Calculate weighted fear score
        total_weight = sum(weight for _, _, weight in fear_components)
        raw_fear = sum(value * weight for _, value, weight in fear_components) / total_weight
        
        # Add to history and smooth
        self.fear_history.append(raw_fear)
        self.fear_score = sum(self.fear_history) / len(self.fear_history)
        
        # Update player profile
        self.player_profile["avg_fear"] = (self.player_profile["avg_fear"] * 0.95 + 
                                           self.fear_score * 0.05)  # Slow moving average
        if self.fear_score > self.player_profile["peak_fear"]:
            self.player_profile["peak_fear"] = self.fear_score
        
        if cv_signals.get("isSmiling"):
            self.player_profile["smiles_during_scares"] += 1
        
        if looking_away:
            self.player_profile["times_looked_away"] += 1
    
    def check_rules_gate(self):
        """Hard constraints - can ANY action be taken?"""
        current_time = time.time()
        time_since_scare = current_time - self.last_scare_time
        time_since_ai_call = current_time - self.last_ai_decision_time
        
        # Don't make decisions during calibration
        if not self.baseline_established:
            return {
                "allowed": False,
                "reason": "waiting_for_baseline",
                "message": "Calibrating player baseline"
            }
        
        # Player not looking - don't waste decisions
        if self.attention_score < 0.4:
            return {
                "allowed": False,
                "reason": "low_attention",
                "message": f"Player not looking (attention: {self.attention_score:.2f})"
            }
        
        # Cooldown on AI calls (don't spam Ollama)
        if time_since_ai_call < self.MIN_AI_CALL_INTERVAL:
            return {
                "allowed": False,
                "reason": "ai_cooldown",
                "message": f"AI cooldown ({self.MIN_AI_CALL_INTERVAL - time_since_ai_call:.1f}s remaining)"
            }
        
        # Check if we're in a good decision window
        if 0.0 <= self.fear_score <= 1.0:  # Always allow
            return {
                "allowed": True,
                "reason": "action_window",
                "fear_zone": self.get_fear_zone(),
                "can_jumpscare": time_since_scare >= self.MIN_SCARE_INTERVAL
            }
        
        return {
            "allowed": False,
            "reason": "fear_out_of_range",
            "message": f"Fear too {'low' if self.fear_score < 0.3 else 'high'} ({self.fear_score:.2f})"
        }
    
    def get_fear_zone(self):
        """Classify current fear level"""
        if self.fear_score < 0.35:
            return "low"
        elif self.fear_score < 0.55:
            return "medium_low"
        elif self.fear_score < 0.75:
            return "medium_high"
        else:
            return "high"
    
    def call_ollama_director(self, rules_output):
        """Ask Ollama what to do"""
        current_time = time.time()
        self.last_ai_decision_time = current_time
        self.total_ai_calls += 1
        
        prompt = f"""You are an expert horror game director. Based on player biometrics and rules, decide what happens next.

RULES ENGINE OUTPUT:
- Jumpscare allowed: {"YES" if rules_output["can_jumpscare"] else "NO (cooldown)"}
- Fear score: {self.fear_score:.2f} ({rules_output["fear_zone"]} - 0=calm, 1=terrified)
- Attention: {self.attention_score:.2f} (player {"looking at screen" if self.attention_score > 0.6 else "distracted"})
- Time since last scare: {current_time - self.last_scare_time:.0f} seconds

PLAYER PROFILE:
- Average fear level: {self.player_profile["avg_fear"]:.2f}
- Peak fear reached: {self.player_profile["peak_fear"]:.2f}
- Total scares received: {self.total_scares_triggered}
- Smiled during scares: {self.player_profile["smiles_during_scares"]} times

IMPORTANT RULES:
- If fear is LOW (< 0.35): Build tension gradually
- If fear is MEDIUM (0.35-0.75): Good jumpscare window (if allowed)
- If fear is HIGH (> 0.75): Give relief, don't overwhelm
- If player smiles often: They're not scared, try psychological horror
- NEVER jumpscare if cooldown not passed

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "action": "jumpscare" | "build_tension" | "relief" | "ambient_event" | "psychological",
  "intensity": 0.0 to 1.0,
  "specifics": "brief description of what happens",
  "reasoning": "one sentence why"
}}"""

        try:
            print(f"🤖 Calling Ollama ({OLLAMA_MODEL})...")
            start_time = time.time()
            
            response = ollama.generate(
                model=OLLAMA_MODEL,
                prompt=prompt,
                stream=False
            )
            
            ai_time = time.time() - start_time
            print(f"✅ Ollama responded in {ai_time:.1f}s")
            
            # Parse response
            raw_text = response['response'].strip()
            
            # Try to extract JSON (Ollama sometimes adds markdown)
            if "```json" in raw_text:
                json_start = raw_text.find("```json") + 7
                json_end = raw_text.find("```", json_start)
                raw_text = raw_text[json_start:json_end].strip()
            elif "```" in raw_text:
                json_start = raw_text.find("```") + 3
                json_end = raw_text.find("```", json_start)
                raw_text = raw_text[json_start:json_end].strip()
            
            decision = json.loads(raw_text)
            
            # Validate required fields
            if "action" not in decision or "intensity" not in decision:
                raise ValueError("Missing required fields")
            
            # Add metadata
            decision["source"] = "ollama"
            decision["model"] = OLLAMA_MODEL
            decision["inference_time"] = ai_time
            
            return decision
            
        except Exception as e:
            self.ai_failures += 1
            print(f"❌ Ollama error: {e}")
            print(f"   Raw response: {response.get('response', 'N/A')[:200]}")
            
            # Fallback to simple rule
            return self.fallback_decision(rules_output)
    
    def fallback_decision(self, rules_output):
        """Simple rule-based fallback if AI fails"""
        fear_zone = rules_output["fear_zone"]
        
        if rules_output["can_jumpscare"] and fear_zone in ["medium_low", "medium_high"]:
            return {
                "action": "jumpscare",
                "intensity": 0.7,
                "specifics": "Standard jumpscare (AI fallback)",
                "reasoning": "Medium fear + high attention = good window",
                "source": "fallback_rules"
            }
        elif fear_zone == "low":
            return {
                "action": "build_tension",
                "intensity": 0.4,
                "specifics": "Ambient sounds, slow music",
                "reasoning": "Fear too low, build gradually",
                "source": "fallback_rules"
            }
        elif fear_zone == "high":
            return {
                "action": "relief",
                "intensity": 0.3,
                "specifics": "Quiet moment, safe area",
                "reasoning": "Fear too high, prevent burnout",
                "source": "fallback_rules"
            }
        else:
            return {
                "action": "sustain",
                "intensity": 0.5,
                "specifics": "Maintain current state",
                "reasoning": "Waiting for better window",
                "source": "fallback_rules"
            }
    
    def make_decision(self):
        """Main decision logic: rules gate + AI decides"""
        rules_output = self.check_rules_gate()
        
        if not rules_output["allowed"]:
            # Rules say no - return simple status
            return {
                "action": "waiting",
                "reason": rules_output["reason"],
                "message": rules_output.get("message", ""),
                "metrics": self.get_metrics()
            }
        
        # Rules say yes - ask AI what to do
        if USE_OLLAMA:
            decision = self.call_ollama_director(rules_output)
        else:
            decision = self.fallback_decision(rules_output)
        
        # Track jumpscare triggers
        if decision["action"] == "jumpscare":
            self.last_scare_time = time.time()
            self.total_scares_triggered += 1
        
        # Add metrics to response
        decision["metrics"] = self.get_metrics()
        
        # Store last decision
        self.last_decision = decision
        
        return decision
    
    def get_metrics(self):
        """Return current metrics"""
        return {
            "fear_score": round(self.fear_score, 2),
            "attention_score": round(self.attention_score, 2),
            "fear_zone": self.get_fear_zone(),
            "baseline_established": self.baseline_established,
            "total_scares": self.total_scares_triggered,
            "total_ai_calls": self.total_ai_calls,
            "ai_failures": self.ai_failures,
            "player_profile": self.player_profile
        }
    
    def get_status(self):
        """Full status for console display"""
        return {
            "metrics": self.get_metrics(),
            "cv_connected": self.cv_connected,
            "last_decision": self.last_decision,
            "ollama_enabled": USE_OLLAMA
        }

# --- GLOBAL INSTANCE ---
director = HybridDirector()

# --- CV MODULE CLIENT ---
async def cv_module_client():
    """Connect to CV module"""
    print(f"🔌 Connecting to CV module at {CV_MODULE_URI}...")
    
    while True:
        try:
            async with websockets.connect(CV_MODULE_URI) as websocket:
                director.cv_connected = True
                print("✅ Connected to CV module")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if "status" not in data:
                            director.update(data)
                    except json.JSONDecodeError:
                        pass
        
        except Exception as e:
            director.cv_connected = False
            print(f"❌ CV connection lost: {e}")
            await asyncio.sleep(2)

# --- UNITY SERVER ---
unity_clients = set()

async def unity_handler(websocket):
    """Handle Unity connections"""
    unity_clients.add(websocket)
    print(f"🎮 Unity connected. Total: {len(unity_clients)}")
    
    try:
        await websocket.send(json.dumps({
            "status": "connected",
            "message": "Hybrid Director ready (rules + Ollama)"
        }))
        
        async for message in websocket:
            try:
                cmd = json.loads(message)
                print(f"📨 Unity: {cmd}")
            except:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        unity_clients.remove(websocket)
        print(f"🎮 Unity disconnected")

async def broadcast_decisions():
    """Send decisions to Unity"""
    while True:
        await asyncio.sleep(UPDATE_RATE)
        
        # Make decision regardless of Unity connection (for testing)
        if director.baseline_established:
            decision = director.make_decision()
            
            # Broadcast to Unity if connected
            if unity_clients and decision["action"] != "waiting":
                message = json.dumps(decision)
                await asyncio.gather(
                    *[client.send(message) for client in unity_clients],
                    return_exceptions=True
                )

async def unity_server():
    """Unity WebSocket server"""
    async with websockets.serve(unity_handler, "localhost", UNITY_SERVER_PORT):
        print(f"🚀 Unity server on ws://localhost:{UNITY_SERVER_PORT}")
        await broadcast_decisions()

# --- CONSOLE STATUS ---
def print_status_loop():
    """Print status to console"""
    while True:
        time.sleep(3)
        
        status = director.get_status()
        metrics = status["metrics"]
        last_dec = status["last_decision"]
        
        print("\n" + "="*70)
        print("🎬 HYBRID DIRECTOR STATUS (Rules + Ollama)")
        print("="*70)
        print(f"CV: {'✅' if status['cv_connected'] else '❌'} | "
              f"Unity: {len(unity_clients)} | "
              f"Baseline: {'✅' if metrics['baseline_established'] else '⏳'} | "
              f"Ollama: {'✅' if status['ollama_enabled'] else '❌ Disabled'}")
        print()
        print(f"😱 FEAR:      {metrics['fear_score']:.2f} {'█' * int(metrics['fear_score'] * 30)} ({metrics['fear_zone']})")
        print(f"👁️  ATTENTION: {metrics['attention_score']:.2f} {'█' * int(metrics['attention_score'] * 30)}")
        print()
        print(f"Stats: {metrics['total_scares']} scares | "
              f"{metrics['total_ai_calls']} AI calls | "
              f"{metrics['ai_failures']} failures")
        print()
        print(f"Last Decision: {last_dec.get('action', 'none').upper()}")
        if last_dec.get('reasoning'):
            print(f"  └─ {last_dec['reasoning']}")
        if last_dec.get('source'):
            print(f"  └─ Source: {last_dec['source']}")
        print("="*70)

# --- MAIN ---
async def main():
    Thread(target=print_status_loop, daemon=True).start()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     🎬 HYBRID HORROR DIRECTOR v2.0 (Rules + Ollama)         ║
╚══════════════════════════════════════════════════════════════╝

Architecture:
  CV Module → Rules Engine → Ollama LLM → Unity
  
Metrics:
  😱 Fear Score:      Weighted combo of scared signals
  👁️  Attention Score: Is player looking at screen
  
Decision Flow:
  1. Rules check: Can we act? (cooldowns, attention)
  2. If YES → Ask Ollama what to do
  3. If NO → Wait for better window
  4. If Ollama fails → Fallback to simple rules

Ollama Model: {OLLAMA_MODEL}
Ollama Enabled: {USE_OLLAMA}

Starting...
""")
    
    await asyncio.gather(
        cv_module_client(),
        unity_server()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")