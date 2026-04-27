
# 🎥 CV Module - Horror Game Computer Vision System

Real-time player behavior tracking via webcam for AI-driven horror game adaptation.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install mediapipe opencv-python numpy websockets
```

### 2. Download Face Model
Download `face_landmarker.task` from [Google's MediaPipe models](https://developers.google.com/mediapipe/solutions/vision/face_landmarker#models) and place it in the same directory as `cv_module.py`.

### 3. Run the CV Module
```bash
python cv_module.py
```

You should see:
```
🚀 WebSocket server started on ws://localhost:8765
⏳ Starting CV pipeline... WebSocket server running in background.
```

### 4. Open Debug Dashboard (Optional)
Open `dashboard.html` in a web browser to see live signal visualization.

### 5. Connect Your Game
Connect to `ws://localhost:8765` from your game engine. You'll immediately start receiving JSON snapshots at ~10 Hz.

---

## 📁 File Guide (Everything Except cv_module.py)

This section explains the other files in this repository and what each is used for.

### Runtime / Integration Files

- `dashboard.html`  
  Live debug dashboard for CV signals over WebSocket (`ws://localhost:8765`). Shows current values, calibration state, and charts.

- `director_agent.py`  
  Rule-based horror director. Consumes CV signals and emits gameplay decisions/actions over a WebSocket server for Unity clients.

- `director_agent_hybrid.py`  
  Hybrid director: rule gate + Ollama text model (`llama3.2`) for creative action selection.

- `visual_fear_detector.py`  
  Separate webcam analysis pipeline using Ollama vision models (for emotion/fear inference). Broadcasts analysis on port `8766`.

### Test / Debug Utilities

- `test_client.html`  
  Minimal browser client that prints raw CV JSON stream from `ws://localhost:8765`.

- `test_director.html`  
  Minimal browser client for director output stream on `ws://localhost:8766`.

- `test_horror_pipeline.py`  
  CLI test harness for dialogue generation flow (camera + prompt + Ollama), without Unity.

### Legacy / Draft / Docs

- `first_working_draft.py`  
  Earlier standalone prototype of the CV pipeline (older calibration/prototyping script).

- `pitch.html`  
  Presentation deck for the project concept and architecture.

- `CACHE_FIX.txt`  
  Patch notes/snippet for fixing stale vision-cache behavior in an external/older server implementation.

### Assets

- `face_landmarker.task`  
  MediaPipe face landmark model file required by the CV stack.

### Notes About Missing / Stale References

- `test_horror_pipeline.py` imports `scene_understander`, but `scene_understander.py` is currently missing from this repo.
- Some prior file listings may mention `director_a` / `scene_understander.py`; they are not present in the current workspace snapshot.

---

## 📡 WebSocket Protocol

### Connection
```javascript
const ws = new WebSocket('ws://localhost:8765');

ws.onopen = () => {
  console.log('Connected to CV module');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Use data.attentionScore, data.blinkDetected, etc.
};
```

### Receiving Data
Every ~100ms, you receive a JSON snapshot. **Two phases:**

#### Phase 1: Calibration (First 20 seconds)
```json
{
  "timestamp": 1714060800.123,
  "faceVisible": true,
  "numFaces": 1,
  "leftBlinkScore": 0.12,
  "rightBlinkScore": 0.08,
  "smileLeft": 0.03,
  "smileRight": 0.02,
  "jawOpen": 0.05,
  "blinkDetected": false,
  "isSmiling": false,
  "mouthOpen": false,
  "headYawDegrees": -5.2,
  "headPitchDegrees": 2.1,
  "lookingAway": false,
  "attentionScore": 0.92,
  "baselineEstablished": false,
  "calibrationSecondsRemaining": 14.3
}
```

#### Phase 2: Post-Calibration (After 20 seconds)
```json
{
  "timestamp": 1714060820.456,
  "faceVisible": true,
  "numFaces": 1,
  "leftBlinkScore": 0.78,
  "rightBlinkScore": 0.82,
  "smileLeft": 0.01,
  "smileRight": 0.01,
  "jawOpen": 0.03,
  "blinkDetected": true,
  "isSmiling": false,
  "mouthOpen": false,
  "headYawDegrees": -12.8,
  "headPitchDegrees": 6.3,
  "lookingAway": false,
  "attentionScore": 0.67,
  "baselineEstablished": true,
  "baselineBlinksPerMin": 14.2,
  "currentBlinksPerMin": 22.5,
  "blinkRateDeviation": 0.58
}
```

#### When Face Not Visible
```json
{
  "timestamp": 1714060830.789,
  "faceVisible": false,
  "secondsSinceFaceVisible": 3.2,
  "attentionScore": 0.36
}
```

### Sending Commands
The game can send commands to the CV module:

```javascript
// Reset baseline calibration (e.g., new player sits down)
ws.send(JSON.stringify({command: 'resetBaseline'}));

// Ping test
ws.send(JSON.stringify({command: 'ping'}));
```

Response:
```json
{
  "status": "ok",
  "message": "Baseline reset initiated"
}
```

---

## 📊 JSON Schema Reference

### Core Fields (Always Present)

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `timestamp` | float | - | Unix timestamp (seconds since epoch) |
| `faceVisible` | bool | - | Is a face detected in frame? |
| `attentionScore` | float | 0.0 - 1.0 | Smoothed engagement metric (see below) |

### Face Detection Fields (When `faceVisible: true`)

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `numFaces` | int | 1+ | Number of faces detected (usually 1) |
| `leftBlinkScore` | float | 0.0 - 1.0 | Left eye closure (0=open, 1=closed) |
| `rightBlinkScore` | float | 0.0 - 1.0 | Right eye closure (0=open, 1=closed) |
| `blinkDetected` | bool | - | True when both eyes >0.5 (edge-detected) |
| `smileLeft` | float | 0.0 - 1.0 | Left mouth corner smile intensity |
| `smileRight` | float | 0.0 - 1.0 | Right mouth corner smile intensity |
| `isSmiling` | bool | - | True when average smile score >0.4 |
| `jawOpen` | float | 0.0 - 1.0 | Jaw opening amount |
| `mouthOpen` | bool | - | True when `jawOpen` >0.3 |
| `headYawDegrees` | float | -90 to +90 | Head rotation left/right (neg=left, pos=right) |
| `headPitchDegrees` | float | -90 to +90 | Head tilt up/down (neg=down, pos=up) |
| `lookingAway` | bool | - | True when head turned >25° in any direction |




### Calibration Fields

| Field | Type | Description |
|-------|------|-------------|
| `baselineEstablished` | bool | False during first 20s, True after |
| `calibrationSecondsRemaining` | float | Countdown during calibration phase |
| `baselineBlinksPerMin` | float | This player's normal blink rate |
| `currentBlinksPerMin` | float | Blinks/min in last 10 seconds |
| `blinkRateDeviation` | float | Deviation from baseline (see interpretation below) |

### Face-Missing Fields (When `faceVisible: false`)

| Field | Type | Description |
|-------|------|-------------|
| `secondsSinceFaceVisible` | float | Time elapsed since face was last seen |

---

## 🧠 Signal Interpretation Guide

### `attentionScore` (0.0 - 1.0)
**What it measures:** Player engagement with the screen.

| Value | Meaning | Director Action |
|-------|---------|-----------------|
| 0.9 - 1.0 | Fully engaged, staring at screen | Safe to deliver story/dialogue |
| 0.6 - 0.9 | Engaged but slightly distracted | Normal gameplay |
| 0.3 - 0.6 | Moderately disengaged, looking away occasionally | Subtle "come back" cues (whispers, screen effects) |
| 0.0 - 0.3 | Highly disengaged or face not visible | Strong attention grab or pause gameplay |

**Calculation:**
- Starts at 1.0
- ×0.3 penalty when `lookingAway: true`
- ×0.7 penalty when blinking excessively
- Decays to 0 over 5 seconds when face disappears
- Smoothed over last 3 seconds

**Use cases:**
- Don't trigger jumpscares if `attentionScore < 0.5` (they won't see it)
- Increase ambient tension if player avoids looking at screen
- Pause story dialogue if `attentionScore < 0.3`

---

### `blinkRateDeviation` (-1.0 to +2.0+)
**What it measures:** How much the player's blink rate differs from their baseline.

| Value | Meaning | Likely Emotional State |
|-------|---------|------------------------|
| -0.5 to -1.0 | Blinking much less than normal | **Deep focus / freeze response** (intense fear or concentration) |
| -0.2 to +0.2 | Near baseline | Calm, neutral |
| +0.3 to +0.7 | Blinking moderately more | **Mild stress / nervousness** |
| +0.8 to +1.5 | Blinking significantly more | **High tension / anxiety** |
| +1.5+ | Blinking excessively | **Extreme stress / discomfort** |

**Important:** Only available after `baselineEstablished: true` (20 seconds in).

**Use cases:**
- If deviation >0.5 for 10+ seconds → player is tense, dial back intensity
- If deviation <-0.3 → player is frozen/focused, good time for jumpscare
- If deviation rapidly spikes from 0.2 to 1.0 → something just scared them

---

### `lookingAway` (boolean)
**What it measures:** Head turned >25° away from screen (left/right/up/down).

**Note:** This is **head pose**, not eye gaze. Player could technically still see the screen peripherally, but turning their head away is a strong avoidance signal.

| State | Meaning |
|-------|---------|
| `false` | Head facing screen (normal) |
| `true` | Head turned away (avoidance behavior) |

**Use cases:**
- If `lookingAway` for 3+ seconds → "Don't look away..." warning
- If player looks away during scary scene → monster pauses or waits
- Track duration: brief glance away vs. sustained avoidance

---

### `blinkDetected` (boolean)
**What it measures:** Edge-detected blink (both eyes >0.5 closure).

**Important:** This is **event-based**. Each blink triggers `true` for 1-3 frames, then returns to `false`. Don't count it multiple times.

**Use cases:**
- Synchronize jumpscares to blinks (happens during eye closure = more startling)
- Track blink frequency for tension gauge
- "The monster moves when you blink" mechanic

---

### `isSmiling` (boolean)
**What it measures:** Both mouth corners raised >0.4.

**Use cases:**
- If player smiles during horror scene → game responds: "You think this is funny?"
- Track emotional dissonance (smiling when scared = nervous laughter)
- Difficulty adaptation: if player smiles too much, increase difficulty

---

### `mouthOpen` (boolean)
**What it measures:** Jaw opening >0.3 (gasping, screaming, talking).

**Use cases:**
- **"It heard you scream"** mechanic (mouth open = sound made)
- Detect surprise reactions (sudden jaw drop)
- Stealth sections where player must stay silent

---

### `headYawDegrees` / `headPitchDegrees` (-90 to +90)
**What it measures:** Precise head orientation.

| Axis | Negative | Positive |
|------|----------|----------|
| Yaw | Head turned left | Head turned right |
| Pitch | Head tilted down | Head tilted up |

**Use cases:**
- Track which direction player looks away (left vs right)
- "Look up" / "Look down" explicit instructions
- Detect head shaking (rapid yaw oscillation) = "no" gesture

---

---

### `proximityDeviation` (-1.0 to +1.0+) & `proximityState`
**What it measures:** How close the player is to the camera compared to their baseline distance.

**Available after:** `baselineEstablished: true` (20 seconds calibration)

| proximityDeviation | proximityState | Meaning |
|-------------------|----------------|---------|
| < -0.15 | `"far"` | Player leaned back / moved away from screen |
| -0.15 to +0.15 | `"normal"` | Player at normal distance |
| > +0.15 | `"close"` | Player leaned in / moved closer to screen |
| N/A | `"calibrating"` | Still establishing baseline |

**How it works:** Tracks face bounding box area. Larger face = closer to camera. During calibration, establishes the player's normal sitting distance, then reports deviations from that baseline.

**Important caveats:**
- **Not true distance measurement** — just relative change from baseline
- **Affected by head angle** — turning head left/right makes face appear smaller even if distance unchanged
- **Per-player variation** — someone with a large face sitting far away looks similar to someone with a small face sitting close

**Use cases:**

| Scenario | Interpretation | Director Action |
|----------|---------------|-----------------|
| `proximityState: "far"` sustained 5+ sec | Player physically avoiding screen (fear/discomfort) | Dial back intensity or trigger "don't hide from me" moment |
| `proximityState: "close"` during tense scene | Player leaning in (engagement/curiosity) | Good time for jumpscare or reveal |
| Rapid changes `"normal" → "far" → "normal"` | Player flinched/recoiled then recovered | Something just scared them |
| `proximityState: "close"` + `attentionScore: 0.9` + low blink rate | Deep immersion | Player is fully absorbed, ideal state |

**Example: Detecting a flinch**
```javascript
let recentProximity = [];

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.proximityDeviation !== undefined) {
    recentProximity.push(data.proximityDeviation);
    
    // Keep last 20 samples (~2 seconds)
    if (recentProximity.length > 20) recentProximity.shift();
    
    // Detect sudden backward movement (flinch)
    if (recentProximity.length >= 10) {
      const recent = recentProximity.slice(-5);  // last 0.5 sec
      const earlier = recentProximity.slice(-10, -5);  // 0.5 sec before that
      
      const recentAvg = recent.reduce((a,b) => a+b) / recent.length;
      const earlierAvg = earlier.reduce((a,b) => a+b) / earlier.length;
      
      // If they suddenly leaned back >20%
      if (earlierAvg - recentAvg > 0.2) {
        console.log("FLINCH DETECTED - player recoiled");
        // The last event scared them!
      }
    }
  }
};
```

**When NOT to use proximity:**
- ❌ **Don't use for precise distance measurement** — it's a relative signal, not absolute cm/inches
- ❌ **Don't penalize players for leaning back** — some people just sit farther from screens naturally
- ⚠️ **Be careful with head-turn false positives** — if player turns head 45° left, face area drops even if they didn't move away

**Recommendation:** Use proximity as a **secondary signal** to confirm interpretations from other metrics. "Player is blinking more + looking away + leaning back = probably uncomfortable" is stronger than any single signal alone.

---

### `faceArea` (0.0 to ~0.1)
**What it measures:** Raw bounding box area of detected face (normalized 0-1 coordinate space).

**Typical values:**
- Close-up (face fills frame): 0.08 - 0.15
- Normal sitting distance: 0.02 - 0.05
- Far away: 0.005 - 0.02

**Use cases:**
- Mostly for debugging proximity issues
- Could track over long periods to detect if player gradually moves closer/farther during gameplay

**Note:** This is the raw measurement used to calculate `proximityDeviation`. You probably want to use `proximityDeviation` or `proximityState` instead, as they're normalized to the player's baseline.

---

### `faceVisible` (boolean)
**What it measures:** Is MediaPipe detecting a face?

| State | Possible Reasons |
|-------|------------------|
| `false` | Player left, covered camera, turned completely away, poor lighting |
| `true` | Face detected |

**Use cases:**
- If `false` for >5 seconds → pause game or show "Please return" message
- If rapidly toggling → warn player about webcam positioning
- Track `secondsSinceFaceVisible` to gauge absence duration

---

## 🎮 Integration Examples

### Example 1: Adaptive Jumpscare Timing
```javascript
let recentData = [];

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  recentData.push(data);
  
  // Keep last 50 snapshots (~5 seconds)
  if (recentData.length > 50) recentData.shift();
};

function shouldTriggerJumpscare() {
  const latest = recentData[recentData.length - 1];
  
  // Don't jumpscare if player isn't looking
  if (latest.attentionScore < 0.5) return false;
  
  // Wait for a blink (eyes closed = more startling)
  if (!latest.blinkDetected) return false;
  
  // Best time: player is focused but slightly tense
  if (latest.blinkRateDeviation > 0.2 && latest.blinkRateDeviation < 0.6) {
    return true;
  }
  
  return false;
}
```

### Example 2: Tension Level Calculation
```javascript
function calculateTensionLevel(data) {
  if (!data.baselineEstablished) return 0.5; // neutral during calibration
  
  let tension = 0.5; // baseline
  
  // Increase tension if blinking more
  if (data.blinkRateDeviation > 0.5) {
    tension += 0.3;
  }
  
  // Increase if looking away (avoidance)
  if (data.lookingAway) {
    tension += 0.2;
  }
  
  // Decrease if smiling (not taking it seriously)
  if (data.isSmiling) {
    tension -= 0.3;
  }
  
  // Decrease if very low blink rate (frozen focus)
  if (data.blinkRateDeviation < -0.4) {
    tension += 0.2; // actually this might be fear!
  }
  
  return Math.max(0, Math.min(1, tension));
}
```

### Example 3: Story Branch Selection
```javascript
function pickDialogueResponse(playerChoice, cvData) {
  // If player seems scared (high blink rate), offer reassurance
  if (cvData.blinkRateDeviation > 0.7) {
    return "CALM_RESPONSE";
  }
  
  // If player seems bored (low attention, smiling), escalate
  if (cvData.attentionScore < 0.4 || cvData.isSmiling) {
    return "ESCALATE_HORROR";
  }
  
  // If player is deeply focused (low blink, high attention), deliver twist
  if (cvData.blinkRateDeviation < -0.3 && cvData.attentionScore > 0.8) {
    return "PLOT_TWIST";
  }
  
  return "NEUTRAL_RESPONSE";
}
```

---

## 🔧 Troubleshooting

### CV module won't start
- **Check Python version:** Requires Python 3.10 or 3.11 (MediaPipe doesn't support 3.12+ on some platforms)
- **Reinstall dependencies:** `pip install --force-reinstall mediapipe opencv-python`
- **Check webcam permissions:** On Mac/Windows, grant camera access to Terminal/CMD

### Game can't connect to WebSocket
- **Firewall:** Ensure localhost port 8765 isn't blocked
- **Check CV module is running:** Look for "WebSocket server started" message
- **Test with dashboard:** Open `dashboard.html` — if it connects, game client code is the issue

### Signals seem wrong/noisy
- **Lighting:** MediaPipe needs decent lighting. Face a window or lamp.
- **Webcam quality:** Integrated laptop webcams work but external HD webcams are better
- **Tune thresholds:** Edit values in `cv_module.py` (blink threshold, smile threshold, head angle threshold)

### Baseline calibration never completes
- **Face must be visible:** Keep face in frame for full 20 seconds
- **Check terminal:** Should print "🎯 BASELINE ESTABLISHED" after 20s
- **Reset if interrupted:** Send `{command: 'resetBaseline'}` via WebSocket

### Dashboard shows "Disconnected"
- **CV module must be running first:** Start Python script before opening dashboard
- **Check browser console:** F12 → Console tab for WebSocket errors
- **Try different browser:** Chrome/Firefox recommended

---

## 🏗️ Architecture Overview

```
┌─────────────────┐
│   Webcam        │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  MediaPipe Face Landmarker  │
│  - 478 face landmarks       │
│  - Blendshapes (52 scores)  │
│  - Head pose matrix         │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Signal Processing          │
│  - Blink edge detection     │
│  - Baseline calibration     │
│  - Attention score smoothing│
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  WebSocket Server (10 Hz)   │
│  ws://localhost:8765        │
└────┬────────────────────┬───┘
     │                    │
     ▼                    ▼
┌─────────┐         ┌──────────┐
│  Game   │         │Dashboard │
│ Engine  │         │  (debug) │
└─────────┘         └──────────┘
```

---

## 📝 Credits

- **MediaPipe:** Google's face detection/tracking
- **OpenCV:** Webcam capture
- **Chart.js:** Dashboard visualization




