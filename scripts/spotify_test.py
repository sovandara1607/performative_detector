"""Small helper to test Spotify playback and controls from the project venv.

Usage:
  python scripts/spotify_test.py status
  python scripts/spotify_test.py play
  python scripts/spotify_test.py next
  python scripts/spotify_test.py prev
  python scripts/spotify_test.py shuffle on|off

This uses the existing .env and .spotify_cache produced by the OAuth step.
"""
import sys
import time
from spotify_controller import SpotifyController


def main():
    c = SpotifyController()
    if len(sys.argv) < 2:
        print('usage: status|play|next|prev|shuffle on|off')
        return
    cmd = sys.argv[1]
    if cmd == 'status':
        print('device_id:', c.device_id)
        if c.sp:
            devs = c.sp.devices()
            print('devices:')
            for d in devs.get('devices', []):
                print('-', d.get('name'), 'active=', d.get('is_active'))
            cur = c.sp.current_playback()
            print('current playback:', cur)
    elif cmd == 'play':
        print('Triggering play (will pick playlist > track list > default)')
        c.play_juna()
    elif cmd == 'next':
        print('Next track')
        c.next_track()
    elif cmd == 'prev':
        print('Previous track')
        c.previous_track()
    elif cmd == 'shuffle' and len(sys.argv) >= 3:
        onoff = sys.argv[2].lower() in ('1', 'true', 'yes', 'on')
        print('Setting shuffle to', onoff)
        c.set_shuffle(onoff)
    else:
        print('Unknown command')


if __name__ == '__main__':
    main()
