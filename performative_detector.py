"""
Performative Detector - Detects if you're holding a matcha (or any cup-like object)
and plays Juna by Clairo on Spotify while displaying "PERFORMATIVE"
"""
import os
import sys
import cv2
import mediapipe as mp
import numpy as np
from spotify_controller import SpotifyController
import time
import subprocess

class PerformativeDetector:
    def __init__(self):
        # Initialize MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.3
        )
        self.mp_draw = mp.solutions.drawing_utils
        
        # Initialize Spotify controller
        self.spotify = SpotifyController()
        
        # State tracking
        self.is_holding = False
        self.holding_start_time = None
        self.holding_duration_threshold = 0.2  # seconds to confirm holding (smooth)
        self.spotify_mode = False  # Track if we're in Spotify display mode
        self.spotify_mode_start_time = None  # Track when Spotify mode started
        self.face_cam_delay = 1.0  # Wait 1 second before showing face cam
        self.face_cam_shown = False  # Track if face cam has been shown
        self.force_top_counter = 0  # Counter to periodically force window to top
        self.status_window_initialized = False  # Track if status window has been positioned
        self.face_cam_positioned = False  # Track if face cam has been positioned (only do once)
        
        # Initialize camera (prefer CAMERA_INDEX env, fall back to common indices)
        self.cap = self.open_camera()
        if self.cap is not None and self.cap.isOpened():
            # Configure preferred size only when camera opened
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        else:
            print("⚠️  Warning: No camera could be opened. The app will exit when trying to read frames.")
        
        print("🎥 Performative Detector Started!")
        print(f"🎵 Spotify: {'Connected' if self.spotify.is_spotify_available() else 'Disabled'}")
        print("📋 Instructions:")
        print("   - Hold a cup/matcha in front of camera to be PERFORMATIVE")
        print("   - Press 'q' to quit")
        # UI state for on-screen buttons
        self.ui_buttons = {}  # name -> (x, y, w, h)
        # detection-repeat controls (tap detection to skip tracks)
        self.detect_count = 0
        self.last_detect_time = 0
        self.detect_window = 1.5  # seconds to count repeat detections
        self.detect_threshold_for_next = 3
        
        # Swipe gesture detection
        self.hand_position_history = []  # Store recent hand positions: [(x, y, timestamp), ...]
        self.max_history_length = 10  # Keep last 10 positions
        self.swipe_cooldown = 1.5  # seconds between swipes
        self.last_swipe_time = 0
        self.swipe_threshold = 0.15  # Minimum horizontal movement (normalized)

        # Create a named Status window and set mouse callback for simple UI buttons
        try:
            cv2.namedWindow('Status', cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
            cv2.resizeWindow('Status', 1200, 800)
            cv2.setMouseCallback('Status', self._on_status_mouse)
        except Exception:
            pass
    
    def detect_holding_gesture(self, hand_landmarks_list, image_shape):
        """
        Detect if hands are in a 'holding' position
        This checks if:
        1. Both hands are visible
        2. Hands are close together (indicating holding something between them)
        3. Hands are in the center region of the frame
        """
        if len(hand_landmarks_list) < 2:
            return False
        
        height, width = image_shape[:2]
        
        # Get center points of both hands
        hand_centers = []
        for hand_landmarks in hand_landmarks_list:
            # Calculate center of hand (average of all landmarks)
            x_coords = [lm.x for lm in hand_landmarks.landmark]
            y_coords = [lm.y for lm in hand_landmarks.landmark]
            center_x = np.mean(x_coords)
            center_y = np.mean(y_coords)
            hand_centers.append((center_x, center_y))
        
        if len(hand_centers) < 2:
            return False
        
        # Calculate distance between hands
        dist = np.sqrt((hand_centers[0][0] - hand_centers[1][0])**2 + 
                      (hand_centers[0][1] - hand_centers[1][1])**2)
        
        # Check if hands are close together (holding something)
        # Made more lenient - increased from 0.3 to 0.5
        if dist < 0.5:  # Normalized distance (0-1)
            # Check if hands are in center-ish area
            avg_x = (hand_centers[0][0] + hand_centers[1][0]) / 2
            avg_y = (hand_centers[0][1] + hand_centers[1][1]) / 2
            
            # Center region check (not at edges) - more lenient
            if 0.1 < avg_x < 0.9 and 0.1 < avg_y < 0.95:
                print(f"🙌 Two hands detected! Distance: {dist:.2f}")
                return True
        
        return False
    
    def detect_single_hand_holding(self, hand_landmarks, image_shape):
        """
        Detect if a single hand is in a holding position
        (fingers partially closed, as if gripping something)
        """
        # Get key landmarks
        wrist = hand_landmarks.landmark[0]
        thumb_tip = hand_landmarks.landmark[4]
        index_tip = hand_landmarks.landmark[8]
        middle_tip = hand_landmarks.landmark[12]
        ring_tip = hand_landmarks.landmark[16]
        pinky_tip = hand_landmarks.landmark[20]
        
        # Get MCP (knuckle) points
        index_mcp = hand_landmarks.landmark[5]
        middle_mcp = hand_landmarks.landmark[9]
        
        # Calculate if fingers are curled (holding position)
        # Fingers are curled if fingertips are below or close to MCP joints
        index_curled = index_tip.y > index_mcp.y - 0.08
        middle_curled = middle_tip.y > middle_mcp.y - 0.08
        
        # Thumb should be somewhat opposed - made more lenient
        thumb_dist = np.sqrt((thumb_tip.x - index_tip.x)**2 + (thumb_tip.y - index_tip.y)**2)
        
        # Check if hand is in center region and fingers show holding gesture - more lenient area
        if 0.1 < wrist.x < 0.9 and 0.1 < wrist.y < 0.95:
            if (index_curled or middle_curled) and thumb_dist < 0.3:
                print(f"👋 Single hand holding detected!")
                return True
        
        return False
    
    def create_status_window(self, text, color, width=1200, height=800):
        """Create a separate window just for status display"""
        # Create a blank canvas
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Fill with background color based on status
        if "PERFORMATIVE" == text:
            # Matcha green tinted background
            canvas[:] = (40, 50, 30)  # Dark matcha green tint
        else:
            # Dark red tinted background
            canvas[:] = (20, 20, 40)  # Dark red tint
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        # LOUD text - large and bold
        scale = 5.0
        thickness = 12
        
        # Split text into lines if it's multi-line
        lines = text.split('\n')
        
        # Calculate total height needed
        line_heights = []
        line_widths = []
        for line in lines:
            text_size = cv2.getTextSize(line, font, scale, thickness)[0]
            line_widths.append(text_size[0])
            line_heights.append(text_size[1])
        
        line_spacing = 30  # Space between lines
        total_height = sum(line_heights) + (len(lines) - 1) * line_spacing
        
        # Calculate starting y position to center all lines
        start_y = (height - total_height) // 2 + line_heights[0]
        
        # Draw each line
        current_y = start_y
        for i, line in enumerate(lines):
            # Center each line horizontally
            text_x = (width - line_widths[i]) // 2
            
            # Draw text with thick black outline for better visibility
            cv2.putText(canvas, line, (text_x, current_y), font, scale, (0, 0, 0), thickness + 8)
            cv2.putText(canvas, line, (text_x, current_y), font, scale, color, thickness)
            
            # Move to next line position
            if i < len(lines) - 1:
                current_y += line_heights[i] + line_spacing
        
        return canvas
    
    def create_face_cam_overlay(self, frame):
        """Create a smaller face cam with hardcoded 'performative' label"""
        # Resize frame to smaller size for PIP (picture-in-picture)
        small_height = 300
        small_width = 400
        small_frame = cv2.resize(frame, (small_width, small_height))
        
        # Add hardcoded "performative" label at the top
        font = cv2.FONT_HERSHEY_SIMPLEX
        label = "performative"
        scale = 1.2
        thickness = 3
        
        # Get text size for centering
        text_size = cv2.getTextSize(label, font, scale, thickness)[0]
        text_x = (small_width - text_size[0]) // 2
        text_y = 40
        
        # Draw semi-transparent background for label
        overlay = small_frame.copy()
        cv2.rectangle(overlay, (0, 0), (small_width, 60), (40, 50, 30), -1)
        cv2.addWeighted(overlay, 0.7, small_frame, 0.3, 0, small_frame)
        
        # Draw text with outline
        cv2.putText(small_frame, label, (text_x, text_y), font, scale, (0, 0, 0), thickness + 2)
        cv2.putText(small_frame, label, (text_x, text_y), font, scale, (100, 200, 100), thickness)
        
        return small_frame

    def open_camera(self):
        """Open a cv2.VideoCapture using CAMERA_INDEX or fallback indices.

        Environment variables:
        - CAMERA_INDEX: single integer index (preferred)
        - CAMERA_CANDIDATES: comma-separated list of indices to try (e.g. "0,1,2")
        """
        # Build candidate list
        candidates = []
        cam_env = os.getenv('CAMERA_INDEX')
        cand_env = os.getenv('CAMERA_CANDIDATES')
        if cam_env is not None:
            try:
                candidates.append(int(cam_env))
            except Exception:
                pass
        if cand_env:
            for part in cand_env.split(','):
                try:
                    idx = int(part.strip())
                    if idx not in candidates:
                        candidates.append(idx)
                except Exception:
                    continue

        # sensible defaults: try 0 then 1
        for default in [0, 1]:
            if default not in candidates:
                candidates.append(default)

        print(f"🔎 Trying camera indices in order: {candidates}")

        # Try platform-specific API preferences when available (helps on macOS)
        api_preferences = [cv2.CAP_ANY]
        if sys.platform.startswith('darwin'):
            api_preferences.insert(0, cv2.CAP_AVFOUNDATION)
        elif sys.platform.startswith('win'):
            api_preferences.insert(0, cv2.CAP_DSHOW)

        for idx in candidates:
            for api in api_preferences:
                try:
                    cap = cv2.VideoCapture(idx, api)
                    # Give camera a moment to initialize
                    time.sleep(0.15)
                    if cap.isOpened():
                        # Try a single read to ensure we have a non-black frame
                        ok, frame = cap.read()
                        mn = None
                        mx = None
                        if ok and frame is not None:
                            try:
                                mn = int(frame.min())
                                mx = int(frame.max())
                            except Exception:
                                mn = None
                                mx = None
                        print(f"attempt idx={idx} api={api} opened=True read={ok} min={mn} max={mx}")
                        # Accept if frame has visible content
                        if ok and frame is not None and mx is not None and mx > 10:
                            print(f"✅ Opened camera at index {idx} using api {api} (validated)")
                            return cap
                        else:
                            try:
                                cap.release()
                            except Exception:
                                pass
                except Exception:
                    try:
                        cap.release()
                    except Exception:
                        pass

        # none worked
        return None

    def reopen_camera_try(self):
        """Try to re-open the camera if a black frame or read failure occurs."""
        try:
            try:
                if self.cap:
                    self.cap.release()
            except Exception:
                pass
            new_cap = self.open_camera()
            if new_cap is not None and new_cap.isOpened():
                # configure preferred size only when camera opened
                new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap = new_cap
                print("🔁 Reopened camera successfully")
                return True
        except Exception:
            pass
        print("⚠️  Could not reopen camera")
        return False
    
    def force_face_cam_to_top(self):
        """Force Face Cam window to be on top using AppleScript (macOS only)"""
        try:
            # More aggressive AppleScript to bring window to front
            applescript = '''
            tell application "System Events"
                tell (first process whose frontmost is true)
                    set windowName to name of first window
                end tell
                
                repeat with proc in processes
                    if name of proc contains "Python" then
                        tell proc
                            repeat with w in windows
                                if name of w is "Face Cam" then
                                    set frontmost to true
                                    perform action "AXRaise" of w
                                    set position of w to {100, 100}
                                    exit repeat
                                end if
                            end repeat
                        end tell
                    end if
                end repeat
            end tell
            '''
            subprocess.Popen(['osascript', '-e', applescript], 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
        except Exception as e:
            pass  # Silently fail if AppleScript doesn't work
    
    def detect_swipe_gesture(self, hand_landmarks, current_time):
        """Detect left/right swipe gestures for track control
        Returns: 'left', 'right', or None
        """
        # Get the center of the hand (wrist position is a good reference)
        wrist = hand_landmarks.landmark[0]
        hand_center_x = wrist.x
        hand_center_y = wrist.y
        
        # Add current position to history
        self.hand_position_history.append((hand_center_x, hand_center_y, current_time))
        
        # Keep only recent history
        if len(self.hand_position_history) > self.max_history_length:
            self.hand_position_history.pop(0)
        
        # Need at least 5 positions to detect a swipe
        if len(self.hand_position_history) < 5:
            return None
        
        # Check if we're still in cooldown
        if current_time - self.last_swipe_time < self.swipe_cooldown:
            return None
        
        # Calculate horizontal movement from oldest to newest position
        oldest_pos = self.hand_position_history[0]
        newest_pos = self.hand_position_history[-1]
        
        horizontal_movement = newest_pos[0] - oldest_pos[0]
        time_span = newest_pos[2] - oldest_pos[2]
        
        # Require movement within reasonable time (not too slow)
        if time_span > 0.8:
            return None
        
        # Detect swipe direction
        if horizontal_movement > self.swipe_threshold:
            print(f"👉 Swipe RIGHT detected (movement: {horizontal_movement:.2f})")
            return 'right'
        elif horizontal_movement < -self.swipe_threshold:
            print(f"👈 Swipe LEFT detected (movement: {horizontal_movement:.2f})")
            return 'left'
        
        return None
    
    def draw_status(self, frame, num_hands):
        """Draw status information at bottom of frame"""
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        # Instructions at bottom
        cv2.putText(frame, "Press 'q' to quit | Swipe left/right to change tracks", 
                   (10, frame.shape[0] - 20), font, 0.6, (200, 200, 200), 1)

    def _on_status_mouse(self, event, x, y, flags, param):
        """Handle mouse clicks on the Status window buttons."""
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for name, rect in (self.ui_buttons or {}).items():
            rx, ry, rw, rh = rect
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                # Map button name to action
                try:
                    if name == 'Next':
                        self.spotify.next_track()
                    elif name == 'Prev':
                        self.spotify.previous_track()
                    elif name == 'Play':
                        if self.spotify.is_playing:
                            self.spotify.pause()
                        else:
                            self.spotify.play_juna()
                    elif name == 'Shuffle':
                        # toggle
                        new_state = not getattr(self.spotify, 'shuffle_enabled', False)
                        self.spotify.set_shuffle(new_state)
                except Exception as e:
                    print('⚠️  UI action failed:', e)
    
    def run(self):
        """Main detection loop"""
        while True:
            if not self.cap or not self.cap.isOpened():
                print("⚠️  Camera is not opened, attempting to reopen...")
                if not self.reopen_camera_try():
                    break

            ret, frame = self.cap.read()
            if not ret:
                print("⚠️  Failed to grab frame from camera — attempting to reopen")
                if not self.reopen_camera_try():
                    break
                # try again on next loop
                time.sleep(0.1)
                continue

            # Basic black-frame detection: if frame is empty or nearly all zeros
            try:
                if frame is None or frame.size == 0:
                    print("⚠️  Received empty frame — trying to reopen camera")
                    if not self.reopen_camera_try():
                        break
                    time.sleep(0.1)
                    continue
                min_val = int(frame.min())
                max_val = int(frame.max())
                if max_val <= 10:
                    print(f"⚠️  Camera frame looks black (min={min_val}, max={max_val}) — attempting reopen")
                    if not self.reopen_camera_try():
                        break
                    time.sleep(0.1)
                    continue
            except Exception:
                # If any pixel ops fail, just continue processing normally
                pass
            
            # Flip frame horizontally for mirror view
            frame = cv2.flip(frame, 1)
            
            # Convert to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Process with MediaPipe Hands
            results = self.hands.process(rgb_frame)
            
            # Check for holding gesture
            holding_detected = False
            num_hands = 0
            
            if results.multi_hand_landmarks:
                hand_landmarks_list = results.multi_hand_landmarks
                num_hands = len(hand_landmarks_list)
                
                # Draw hand landmarks
                for hand_landmarks in hand_landmarks_list:
                    self.mp_draw.draw_landmarks(
                        frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS
                    )
                
                # Detect swipe gestures on first hand (only when already performative)
                if len(hand_landmarks_list) > 0 and self.is_holding:
                    swipe_direction = self.detect_swipe_gesture(hand_landmarks_list[0], current_time)
                    if swipe_direction and self.spotify.is_spotify_available():
                        self.last_swipe_time = current_time
                        try:
                            if swipe_direction == 'right':
                                print("⏭️  Next track")
                                self.spotify.next_track()
                            elif swipe_direction == 'left':
                                print("⏮️  Previous track")
                                self.spotify.previous_track()
                            # Clear history after successful swipe
                            self.hand_position_history = []
                        except Exception as e:
                            print(f'⚠️  Track change failed: {e}')
                elif len(hand_landmarks_list) > 0 and not self.is_holding:
                    # Just update position history without detecting swipes (during initial detection)
                    wrist = hand_landmarks_list[0].landmark[0]
                    self.hand_position_history.append((wrist.x, wrist.y, current_time))
                    if len(self.hand_position_history) > self.max_history_length:
                        self.hand_position_history.pop(0)
                
                # Simplified: Any hands detected = PERFORMATIVE!
                holding_detected = True
            
            # Update holding state with debouncing
            current_time = time.time()

            if holding_detected:
                if self.holding_start_time is None:
                    self.holding_start_time = current_time
                elif current_time - self.holding_start_time > self.holding_duration_threshold:
                    if not self.is_holding:
                        self.is_holding = True
                        self.spotify_mode = True  # Enter Spotify mode
                        self.spotify_mode_start_time = current_time  # Record when we entered Spotify mode
                        print("✨ PERFORMATIVE DETECTED!")
                        # handle repeat-detection counting (tap detection to skip tracks)
                        if current_time - self.last_detect_time <= self.detect_window:
                            self.detect_count += 1
                        else:
                            self.detect_count = 1
                        self.last_detect_time = current_time
                        if self.detect_count >= self.detect_threshold_for_next:
                            try:
                                print("⏭️  Detected repeated performative — skipping to next track")
                                self.spotify.next_track()
                            except Exception as e:
                                print('⚠️  next_track failed:', e)
                            self.detect_count = 0
                        else:
                            if self.spotify.is_spotify_available():
                                self.spotify.play_juna()
            else:
                # Clear hand position history when no hands detected
                self.hand_position_history = []
                self.holding_start_time = None
                if self.is_holding:
                    self.is_holding = False
                    print("😐 Not performative anymore")
                    # Note: We don't pause the song - let it keep playing!
            
            # Create status display window
            if self.is_holding:
                # Matcha green color (BGR format)
                status_display = self.create_status_window("PERFORMATIVE", (100, 200, 100))
            else:
                # Bright red color (BGR format) - split into two lines
                status_display = self.create_status_window("NOT\nPERFORMATIVE", (0, 0, 255))

            # Draw small control buttons at top-left of Status window
            # Buttons: Prev | Play/Pause | Next | Shuffle
            try:
                btn_x = 20
                btn_y = 20
                btn_w = 140
                btn_h = 60
                gap = 10
                buttons = ['Prev', 'Play', 'Next', 'Shuffle']
                self.ui_buttons = {}
                for i, b in enumerate(buttons):
                    x = btn_x + i * (btn_w + gap)
                    y = btn_y
                    cv2.rectangle(status_display, (x, y), (x + btn_w, y + btn_h), (50, 50, 50), -1)
                    label = b
                    if b == 'Play':
                        label = 'Pause' if getattr(self.spotify, 'is_playing', False) else 'Play'
                    txt_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                    txt_x = x + (btn_w - txt_size[0]) // 2
                    txt_y = y + (btn_h + txt_size[1]) // 2
                    cv2.putText(status_display, label, (txt_x, txt_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
                    self.ui_buttons[b] = (x, y, btn_w, btn_h)
            except Exception:
                # If drawing fails, ignore UI
                self.ui_buttons = {}

            self.draw_status(frame, num_hands)

            # Display windows based on mode
            cv2.imshow('Status', status_display)
            
            if self.spotify_mode:
                # Check if enough time has passed since entering Spotify mode
                time_in_spotify_mode = current_time - self.spotify_mode_start_time if self.spotify_mode_start_time else 0
                
                if time_in_spotify_mode >= self.face_cam_delay:
                    # Spotify mode: Show small face cam with label after delay
                    face_cam_overlay = self.create_face_cam_overlay(frame)
                    
                    # Create window if first time
                    if not self.face_cam_shown:
                        cv2.namedWindow('Face Cam', cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_EXPANDED)
                        cv2.resizeWindow('Face Cam', 400, 300)
                        self.face_cam_shown = True
                        self.face_cam_positioned = False  # Reset position flag
                        print("📹 Face Cam window created")
                    
                    cv2.imshow('Face Cam', face_cam_overlay)
                    
                    # Only position window once so user can move it
                    if not self.face_cam_positioned:
                        cv2.moveWindow('Face Cam', 100, 100)
                        self.face_cam_positioned = True
                    
                    # Try to set topmost property
                    try:
                        cv2.setWindowProperty('Face Cam', cv2.WND_PROP_TOPMOST, 1)
                    except:
                        pass
                    
                    # Force window to top periodically (every 10 frames)
                    self.force_top_counter += 1
                    if self.force_top_counter % 10 == 0:
                        self.force_face_cam_to_top()
                    
                    # Destroy the full camera feed window if it exists
                    try:
                        cv2.destroyWindow('Camera Feed')
                    except:
                        pass
                else:
                    # Still showing full camera during delay period
                    cv2.imshow('Camera Feed', frame)
            else:
                # Normal mode: Show full camera feed
                cv2.imshow('Camera Feed', frame)
                
                # Destroy the face cam window if it exists
                try:
                    cv2.destroyWindow('Face Cam')
                    self.face_cam_positioned = False  # Reset so it gets positioned again next time
                except:
                    pass
            
            # Check for quit (10ms wait allows better mouse click responsiveness)
            if cv2.waitKey(10) & 0xFF == ord('q'):
                print("\n👋 Closing Performative Detector...")
                break
        
        # Cleanup
        self.cap.release()
        cv2.destroyAllWindows()
        self.hands.close()

def main():
    detector = PerformativeDetector()
    detector.run()

if __name__ == "__main__":
    main()

