"""
Spotify controller module for playing specific songs
"""
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import subprocess
import threading
import random
from dotenv import load_dotenv

load_dotenv()

class SpotifyController:
    def __init__(self):
        self.sp = None
        self.device_id = None
        self.is_playing = False
        self.current_track_uri = None
        self.target_track_uri = "spotify:track:2mWfVxEo4xZYDaz0v7hYrN"  # Juna by Clairo
        self.window_opened = False  # Track if we've already opened the window
        # Optional: playlist or multiple tracks from environment
        self.playlist_uri = os.getenv('SPOTIFY_PLAYLIST_URI')
        # normalize playlist uri if provided without spotify: prefix
        if self.playlist_uri and not self.playlist_uri.startswith('spotify:'):
            if 'http' in self.playlist_uri and 'playlist' in self.playlist_uri:
                parts = self.playlist_uri.split('/')
                pid = parts[-1].split('?')[0]
                self.playlist_uri = f'spotify:playlist:{pid}'
            else:
                pid = self.playlist_uri.split('?')[0]
                self.playlist_uri = f'spotify:playlist:{pid}'

        track_uris_env = os.getenv('SPOTIFY_TRACK_URIS')
        if track_uris_env:
            # comma-separated list of spotify:track:... URIs or IDs
            raw = [t.strip() for t in track_uris_env.split(',') if t.strip()]
            normalized = []
            for t in raw:
                if t.startswith('spotify:'):
                    normalized.append(t)
                elif 'http' in t and 'track' in t:
                    parts = t.split('/')
                    tid = parts[-1].split('?')[0]
                    normalized.append(f'spotify:track:{tid}')
                else:
                    tid = t.split('?')[0]
                    normalized.append(f'spotify:track:{tid}')
            self.track_uris = normalized
        else:
            self.track_uris = []
        # Force using the local Spotify app (AppleScript) even if Web API might work
        self.force_local = str(os.getenv('SPOTIFY_FORCE_LOCAL', '0')).lower() in ('1', 'true', 'yes')
        # Shuffle behavior (env var SPOTIFY_SHUFFLE=1/true to enable)
        shuffle_env = os.getenv('SPOTIFY_SHUFFLE', '0')
        self.shuffle_enabled = str(shuffle_env).lower() in ('1', 'true', 'yes')
        self._initialize_spotify()
    
    def _initialize_spotify(self):
        """Initialize Spotify client with OAuth"""
        try:
            client_id = os.getenv('SPOTIFY_CLIENT_ID')
            client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
            redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
            
            if not client_id or not client_secret:
                print("⚠️  Spotify credentials not found. Music playback disabled.")
                print("   Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env file")
                return
            
            scope = "user-modify-playback-state user-read-playback-state"
            
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                cache_path=".spotify_cache"
            ))
            
            # Get available devices
            devices = self.sp.devices()
            if devices['devices']:
                self.device_id = devices['devices'][0]['id']
                print(f"✓ Spotify connected to device: {devices['devices'][0]['name']}")
            else:
                print("⚠️  No active Spotify devices found. Please open Spotify on a device.")
            # Check if user has Premium subscription (required for remote playback API)
            try:
                user = self.sp.current_user()
                product = user.get('product', '')
                # 'premium' or 'open' (free). Some accounts show different values or empty.
                # If product is empty but we have a device, assume Premium (API working = Premium)
                if product in ('premium', 'unlimited'):
                    self.is_premium = True
                    print(f"✓ Spotify Premium detected (product: {product})")
                elif product == '' or product is None:
                    # Empty product but API works = likely Premium
                    self.is_premium = True
                    print("✓ Spotify Premium assumed (API is functional)")
                else:
                    self.is_premium = False
                    print(f"ℹ️  Spotify product type: {product} — Web API playback may fallback to local app.")
            except Exception as e:
                # Default to True since user confirmed Premium
                self.is_premium = True
                print(f"ℹ️  Could not determine Spotify account type ({e}); assuming Premium.")
                
        except Exception as e:
            print(f"⚠️  Failed to initialize Spotify: {e}")
            self.sp = None
    
    def show_spotify_window(self):
        """Show and enlarge Spotify window using AppleScript (macOS only) - non-blocking"""
        if self.window_opened:
            return  # Already opened, don't do it again
        
        try:
            # AppleScript to activate Spotify and make window large
            applescript = '''
            tell application "Spotify"
                activate
                tell application "System Events"
                    tell process "Spotify"
                        set frontmost to true
                        -- Try to maximize window
                        try
                            tell window 1
                                set position to {100, 100}
                                set size to {800, 600}
                            end tell
                        end try
                    end tell
                end tell
            end tell
            '''
            # Run in background to avoid blocking
            subprocess.Popen(['osascript', '-e', applescript], 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
            self.window_opened = True
            print("🎵 Spotify window opened")
        except Exception as e:
            print(f"⚠️  Could not control Spotify window: {e}")
    
    def _play_target_track_async(self):
        """Play the single target track (self.target_track_uri) with API, fallback to AppleScript if needed."""
        try:
            
            # Refresh device id in case devices changed since init
            try:
                devices = self.sp.devices()
                if devices and devices.get('devices'):
                    # prefer an active device if available
                    active = next((d for d in devices['devices'] if d.get('is_active')), None)
                    chosen = active or devices['devices'][0]
                    self.device_id = chosen.get('id')
            except Exception:
                # ignore device refresh errors and continue with previous device_id
                pass

            current = self.sp.current_playback()
            if current and current.get('item'):
                current_uri = current['item']['uri']
                if current_uri == self.target_track_uri and current['is_playing']:
                    return True

            self.sp.start_playback(device_id=self.device_id, uris=[self.target_track_uri])
            self.is_playing = True
            print("🎵 Playing: Juna by Clairo")
            self.show_spotify_window()
            return True
        except Exception as e:
            msg = str(e)
            print(f"⚠️  Failed to play track via Web API: {msg}")
            if 'PREMIUM_REQUIRED' in msg.upper() or 'PREMIUM' in msg.upper():
                try:
                    applescript = f'''\
                    tell application "Spotify"
                        activate
                        play track "{self.target_track_uri}"
                    end tell
                    '''
                    subprocess.Popen(['osascript', '-e', applescript], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("🎵 Requested local Spotify app to play the track via AppleScript (fallback)")
                    self.show_spotify_window()
                    return True
                except Exception as e2:
                    print(f"⚠️  AppleScript fallback failed: {e2}")
                    return False
            return False

    def _play_tracks_async(self, uris):
        """Play a list of track URIs via API or fallback to AppleScript for the first track."""
        # If forced local or not premium, use AppleScript to play first track (or a shuffle of first)
        # Refresh devices before making API calls
        try:
            devices = self.sp.devices()
            if devices and devices.get('devices'):
                active = next((d for d in devices['devices'] if d.get('is_active')), None)
                chosen = active or devices['devices'][0]
                self.device_id = chosen.get('id')
        except Exception:
            pass

        if self.force_local or not getattr(self, 'is_premium', False):
            if uris:
                try:
                    first = uris[0]
                    applescript = f'''\
                    tell application "Spotify"
                        activate
                        play track "{first}"
                    end tell
                    '''
                    subprocess.Popen(['osascript', '-e', applescript], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("🎵 Requested local Spotify app to play the first track via AppleScript (forced/non-premium)")
                    self.show_spotify_window()
                    return True
                except Exception as e:
                    print(f"⚠️  AppleScript forced/local play failed: {e}")
                    # fall through to API attempt
        try:
            # If already playing one of these tracks and playing, skip
            current = self.sp.current_playback()
            if current and current.get('item'):
                cur_uri = current['item']['uri']
                if cur_uri in uris and current['is_playing']:
                    return True

            play_uris = list(uris)
            if self.shuffle_enabled:
                random.shuffle(play_uris)
            self.sp.start_playback(device_id=self.device_id, uris=play_uris)
            self.is_playing = True
            print(f"🎵 Playing {len(uris)} tracks (first: {uris[0]})")
            self.show_spotify_window()
            return True
        except Exception as e:
            msg = str(e)
            print(f"⚠️  Failed to play tracks via Web API: {msg}")
            # Fallback: play first track in local app
            if uris:
                try:
                    applescript = f'''\
                    tell application "Spotify"
                        activate
                        play track "{uris[0]}"
                    end tell
                    '''
                    subprocess.Popen(['osascript', '-e', applescript], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("🎵 Requested local Spotify app to play the first track via AppleScript (fallback)")
                    self.show_spotify_window()
                    return True
                except Exception as e2:
                    print(f"⚠️  AppleScript fallback failed: {e2}")
                    return False
            return False

    def _play_playlist_async(self):
        """Play a playlist context URI via API, fallback to opening the playlist locally."""
        try:
            if not self.playlist_uri:
                return False

            # Refresh devices and choose an active device if possible
            try:
                devices = self.sp.devices()
                if devices and devices.get('devices'):
                    active = next((d for d in devices['devices'] if d.get('is_active')), None)
                    chosen = active or devices['devices'][0]
                    self.device_id = chosen.get('id')
            except Exception:
                pass

            # If forced local or not premium, attempt to play the first track of the playlist locally
            if self.force_local or not getattr(self, 'is_premium', False):
                # Try to fetch the first track uri from the playlist and play it via AppleScript
                try:
                    # playlist id is the last part of spotify:playlist:<id>
                    pid = self.playlist_uri.split(':')[-1]
                    items = self.sp.playlist_items(pid, limit=1)
                    if items and items.get('items'):
                        first_item = items['items'][0]
                        track = first_item.get('track')
                        if track and track.get('uri'):
                            first_uri = track['uri']
                            applescript = f'''\
                            tell application "Spotify"
                                activate
                                play track "{first_uri}"
                            end tell
                            '''
                            subprocess.Popen(['osascript', '-e', applescript], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            print("🎵 Requested local Spotify app to play the first track of the playlist via AppleScript (forced/non-premium)")
                            self.show_spotify_window()
                            return True
                except Exception as e:
                    print(f"⚠️  Could not fetch playlist contents for local play: {e}")

            # Try API playback of the playlist context
            self.sp.start_playback(device_id=self.device_id, context_uri=self.playlist_uri)
            self.is_playing = True
            print(f"🎵 Playing playlist: {self.playlist_uri}")
            self.show_spotify_window()
            return True
        except Exception as e:
            msg = str(e)
            print(f"⚠️  Failed to play playlist via Web API: {msg}")
            # Fallback: try to open the playlist and also try to play its first track
            try:
                applescript = f'''\
                tell application "Spotify"
                    activate
                    open location "{self.playlist_uri}"
                end tell
                '''
                subprocess.Popen(['osascript', '-e', applescript], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Also try to fetch first track and play it locally (best-effort)
                try:
                    pid = self.playlist_uri.split(':')[-1]
                    items = self.sp.playlist_items(pid, limit=1)
                    if items and items.get('items'):
                        first_item = items['items'][0]
                        track = first_item.get('track')
                        if track and track.get('uri'):
                            first_uri = track['uri']
                            applescript2 = f'''\
                            tell application "Spotify"
                                activate
                                play track "{first_uri}"
                            end tell
                            '''
                            subprocess.Popen(['osascript', '-e', applescript2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

                print("🎵 Requested local Spotify app to open the playlist via AppleScript (fallback)")
                self.show_spotify_window()
                return True
            except Exception as e2:
                print(f"⚠️  AppleScript fallback failed: {e2}")
                return False

    # Playback control helpers
    def next_track(self):
        """Skip to the next track via API or AppleScript fallback."""
        if not self.sp:
            return False
        try:
            self.sp.next_track(device_id=self.device_id)
            return True
        except Exception as e:
            print(f"⚠️  API next_track failed: {e}; trying AppleScript fallback")
            try:
                subprocess.Popen(['osascript', '-e', 'tell application "Spotify" to next track'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception as e2:
                print(f"⚠️  AppleScript next fallback failed: {e2}")
                return False

    def previous_track(self):
        """Go to previous track via API or AppleScript fallback."""
        if not self.sp:
            return False
        try:
            self.sp.previous_track(device_id=self.device_id)
            return True
        except Exception as e:
            print(f"⚠️  API previous_track failed: {e}; trying AppleScript fallback")
            try:
                subprocess.Popen(['osascript', '-e', 'tell application "Spotify" to previous track'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception as e2:
                print(f"⚠️  AppleScript previous fallback failed: {e2}")
                return False

    def set_shuffle(self, state: bool):
        """Enable or disable shuffle on the active device. Returns True on success."""
        if not self.sp:
            return False
        try:
            self.sp.shuffle(state, device_id=self.device_id)
            self.shuffle_enabled = state
            print(f"🔀 Shuffle set to {state}")
            return True
        except Exception as e:
            print(f"⚠️  Failed to set shuffle via API: {e}")
            return False
    
    def play_juna(self):
        """Play 'Juna by Clairo' on Spotify - non-blocking"""
        if not self.sp:
            return False
        # Prefer playlist, then configured track list, then target track
        if self.playlist_uri:
            target = self._play_playlist_async
            args = ()
        elif self.track_uris:
            target = self._play_tracks_async
            args = (self.track_uris,)
        else:
            target = self._play_target_track_async
            args = ()

        # Run in background thread to avoid blocking
        thread = threading.Thread(target=lambda: target(*args), daemon=True)
        thread.start()
        return True
    
    def pause(self):
        """Pause playback"""
        if not self.sp or not self.is_playing:
            return
        
        try:
            self.sp.pause_playback(device_id=self.device_id)
            self.is_playing = False
            print("⏸️  Paused playback")
        except Exception as e:
            print(f"⚠️  Failed to pause: {e}")
    
    def is_spotify_available(self):
        """Check if Spotify is available and ready"""
        return self.sp is not None and self.device_id is not None

