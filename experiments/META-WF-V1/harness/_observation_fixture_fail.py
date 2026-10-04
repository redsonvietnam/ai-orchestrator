import sys
print("STDOUT_FAILURE")
print("STDERR_FAILURE", file=sys.stderr)
raise SystemExit(7)
