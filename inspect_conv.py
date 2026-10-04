import sys, glob, re, os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
files = sorted(
    glob.glob(r"D:\ai-orchestrator\runs\phase1-claude.response.conv.json\*.txt"),
    key=lambda p: int(re.search(r"_(\d+)\.txt$", p).group(1)),
)
print("files:", len(files), "last:", os.path.basename(files[-1]))
c = open(files[-1], encoding="utf-8", errors="replace").read()
print("total chars:", len(c))

# all assistant JSON outputs across last file
outs = re.findall(r'\{\s*"memory".*?\n\}', c, re.S)
print("assistant outputs in last file:", len(outs))
if outs:
    print("=== LAST OUTPUT ===")
    print(outs[-1][:1500])

# progress markers
for marker in ["LOGIN_OK", "todo", "argparse", "```python", "def add", "done"]:
    print(f"contains {marker!r}:", marker.lower() in c.lower())
