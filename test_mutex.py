import ctypes
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
h = k32.CreateMutexW(None, False, "Local\\ai_mutex_test")
err = ctypes.get_last_error()
print(f"handle={h} err={err}", flush=True)
if err == 183:
    sys.exit(1)
time.sleep(8)
print("held for 8s", flush=True)
