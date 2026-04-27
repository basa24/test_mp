"""
Horror Pipeline Tester
=======================
Standalone test harness for debugging the horror dialogue generation.
No Unity required — just you, your webcam, and the terminal.

Usage:
  python test_horror_pipeline.py

Press Enter to capture webcam + generate dialogue.
Type 'quit' to exit.
"""

import json
import logging
import sys
import time
from pathlib import Path

import cv2
import requests

# Import your scene analyzer
sys.path.insert(0, str(Path(__file__).parent))
from scene_understander import analyze_frame

# ─── CONFIG ───────────────────────────────────────────────────────────────────

CONFIG = {
    "ollama_url": "http://localhost:11434/api/generate",
    "ollama_model": "llama3.2",
    "vision_cache_ttl": 5.0,  # Refresh webcam every N seconds
}

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("horror_test")

# ─── VISION CACHE (with TTL fix) ──────────────────────────────────────────────

_vision_cache = {"snapshot": None, "timestamp": 0.0}


def get_player_state() -> str:
    """Capture webcam with TTL-based caching."""
    now = time.monotonic()
    
    # Only use cache if fresh enough
    if _vision_cache["snapshot"] and (now - _vision_cache["timestamp"]) < CONFIG["vision_cache_ttl"]:
        age = now - _vision_cache["timestamp"]
        log.info("📷 Vision cache hit (%.1fs old)", age)
        return _vision_cache["snapshot"]
    
    # Otherwise refresh
    log.info("📷 Capturing webcam...")
    cap = None
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "Camera unavailable."
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Warm up camera
        for _ in range(2):
            cap.read()
        
        ret, frame = cap.read()
        if not ret:
            return "Could not capture frame."

        description = analyze_frame(frame)
        
        # Update cache
        _vision_cache["snapshot"] = description
        _vision_cache["timestamp"] = now
        
        log.info("✓ Vision: %s", description[:100] + "..." if len(description) > 100 else description)
        return description

    except Exception as exc:
        log.error("Vision error: %s", exc)
        return f"Vision error: {exc}"
    finally:
        if cap:
            cap.release()


# ─── PROMPT (same as server) ──────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the Horror Director — the unseen intelligence behind a horror visual novel.

You receive:
1. Game state: NPC name, scene, mood, player's last choice.
2. A webcam observation of the real human player sitting in front of the screen RIGHT NOW.

Your job: write 1-3 sentences of NPC dialogue that feels unnervingly aware of the real player.

RULES:
- You MUST directly reference a specific physical detail from the webcam observation.
  If they wear glasses — mention it. If the room is dark — use it. If they looked away — call it out.
  The NPC should feel like it is literally watching the player through the screen.
- The reference must feel supernatural, not like a coincidence.
- Never say "I can see you" or break the fourth wall directly.
  Instead, weave it in: "Those glasses of yours..." or "The darkness suits you..." or "You looked away just now..."
- Fit the NPC's personality and scene.
- End with implicit dread, never a cheap jump-scare line.

Example — if player has glasses and room is dim:
  "I've always appreciated those who see the world through a lens... it makes it so much easier 
   to watch them when the lights go low."

Respond ONLY with valid JSON:
{
  "dialogue": "...",
  "intensity": 0.0
}"""


def build_prompt(npc_name: str, scene: str, mood: str, player_choice: str, player_state: str) -> str:
    return f"""GAME STATE:
NPC: {npc_name}
Scene: {scene}
NPC Mood: {mood}
Player's Last Choice: {player_choice}

PLAYER OBSERVATION (webcam):
{player_state}

Generate the NPC dialogue now."""


# ─── LLM CALL ─────────────────────────────────────────────────────────────────

def call_horror_llm(prompt: str) -> dict:
    """Call Ollama. Returns {"dialogue": str, "intensity": float}."""
    payload = {
        "model": CONFIG["ollama_model"],
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "format": "json",
    }
    try:
        log.info("🧠 Calling Ollama (%s)...", CONFIG["ollama_model"])
        resp = requests.post(CONFIG["ollama_url"], json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json().get("response", "{}")
        result = json.loads(raw)
        dialogue = result.get("dialogue", "...")
        try:
            intensity = max(0.0, min(1.0, float(result.get("intensity", 0.5))))
        except (ValueError, TypeError):
            intensity = 0.5
        return {"dialogue": dialogue, "intensity": intensity}
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Cannot reach Ollama at {CONFIG['ollama_url']}. Is Ollama running?")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}")


# ─── INTERACTIVE LOOP ─────────────────────────────────────────────────────────

MOCK_SCENARIOS = [
    {
        "npc_name": "The Pale Lady",
        "scene": "chapel_hallway",
        "mood": "suspicious",
        "player_choice": "I chose to open the door",
    },
    {
        "npc_name": "Dr. Harrow",
        "scene": "abandoned_laboratory",
        "mood": "clinical",
        "player_choice": "I examined the surgical tools",
    },
    {
        "npc_name": "The Whisperer",
        "scene": "endless_stairwell",
        "mood": "amused",
        "player_choice": "I kept climbing upward",
    },
]


def main():
    print("═" * 60)
    print("  HORROR PIPELINE TEST HARNESS")
    print("  (No Unity required)")
    print("═" * 60)
    print(f"\n  Vision cache TTL: {CONFIG['vision_cache_ttl']}s")
    print(f"  Ollama: {CONFIG['ollama_model']} @ {CONFIG['ollama_url']}\n")
    print("  Press ENTER to generate dialogue")
    print("  Type 'quit' to exit\n")
    
    scenario_idx = 0
    
    while True:
        try:
            user_input = input(">>> ").strip().lower()
            
            if user_input == "quit":
                print("\n👋 Goodbye!")
                break
            
            # Cycle through mock scenarios
            scenario = MOCK_SCENARIOS[scenario_idx % len(MOCK_SCENARIOS)]
            scenario_idx += 1
            
            print(f"\n{'─' * 60}")
            print(f"🎭 NPC: {scenario['npc_name']}")
            print(f"📍 Scene: {scenario['scene']}")
            print(f"😶 Mood: {scenario['mood']}")
            print(f"💭 Player choice: {scenario['player_choice']}")
            print(f"{'─' * 60}\n")
            
            # 1. Get player state (with cache)
            player_state = get_player_state()
            
            # 2. Build prompt
            prompt = build_prompt(
                scenario["npc_name"],
                scenario["scene"],
                scenario["mood"],
                scenario["player_choice"],
                player_state,
            )
            
            # 3. Call LLM
            result = call_horror_llm(prompt)
            
            # 4. Display result
            print(f"\n💀 DIALOGUE [{result['intensity']*100:.0f}% intensity]:")
            print(f"   \"{result['dialogue']}\"\n")
            
            print(f"📝 Player state used:")
            print(f"   {player_state}\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted. Goodbye!")
            break
        except Exception as exc:
            log.error("Error: %s", exc)
            print(f"\n❌ Error: {exc}\n")


if __name__ == "__main__":
    main()
