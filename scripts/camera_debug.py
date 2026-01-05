#!/usr/bin/env python3
"""
Camera debug helper — tries indices and backends, captures a frame and saves it.
Run from project root with the virtualenv active.
"""
import cv2
import sys
import time
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), 'debug_outputs')
os.makedirs(OUT_DIR, exist_ok=True)

backends = []
if sys.platform.startswith('darwin'):
    backends = [
        (cv2.CAP_AVFOUNDATION, 'AVFOUNDATION'),
        (cv2.CAP_ANY, 'ANY'),
    ]
elif sys.platform.startswith('win'):
    backends = [
        (cv2.CAP_DSHOW, 'DSHOW'),
        (cv2.CAP_MSMF, 'MSMF'),
        (cv2.CAP_ANY, 'ANY'),
    ]
else:
    backends = [
        (cv2.CAP_V4L2 if hasattr(cv2, 'CAP_V4L2') else cv2.CAP_ANY, 'V4L2' if hasattr(cv2, 'CAP_V4L2') else 'ANY'),
        (cv2.CAP_ANY, 'ANY'),
    ]

max_index = 3

print('Camera debug — writing images to', OUT_DIR)

results = []
for idx in range(0, max_index + 1):
    for api, api_name in backends:
        desc = f'idx={idx} api={api_name}'
        print('\n--- Trying', desc)
        try:
            cap = cv2.VideoCapture(idx, api)
            time.sleep(0.15)
            opened = bool(cap.isOpened())
            print('isOpened:', opened)
            ok = False
            frame = None
            if opened:
                ok, frame = cap.read()
            print('read ok:', ok)
            if frame is None:
                print('frame is None')
            else:
                print('shape:', getattr(frame, 'shape', None), 'dtype:', getattr(frame, 'dtype', None))
                try:
                    mn = int(frame.min())
                    mx = int(frame.max())
                except Exception:
                    mn = None
                    mx = None
                print('min/max:', mn, mx)

                # write file if non-empty
                outname = os.path.join(OUT_DIR, f'capture_idx{idx}_{api_name}.png')
                try:
                    cv2.imwrite(outname, frame)
                    print('wrote', outname)
                except Exception as e:
                    print('failed to write image:', e)

            results.append({'idx': idx, 'api': api_name, 'opened': opened, 'read': ok, 'min': mn, 'max': mx})
        except Exception as e:
            print('exception while trying:', e)
        finally:
            try:
                cap.release()
            except Exception:
                pass

print('\nSummary:')
for r in results:
    print(r)

print('\nDone.')
