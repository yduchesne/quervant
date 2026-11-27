import json
from pathlib import Path
import subprocess
import sys

# Usage: run_contract.py CONTRACT RECEIPTS_ROOT RECORDER CLASSIFICATION
contract_path, receipts_root, recorder, classification = sys.argv[1:]
assert classification in {"BASELINE", "PASS"}
root = Path(receipts_root).resolve()
assert root.is_absolute()
contract = json.loads(Path(contract_path).read_text())
for item in contract["receipts"]:
    if item["classification"] != classification:
        continue
    destination = root / item["path"]
    assert not destination.exists(), str(destination)
    command = [sys.executable, str(Path(recorder).resolve()),
               str(destination), item["commit"], item["label"], *item["argv"]]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
