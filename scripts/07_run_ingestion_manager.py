# 07_run_ingestion_manager.py
# Run ingestion pipeline to process HotpotQA data and produce FAISS artifacts.

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.managers.ingestion_manager import IngestionManager, IngestionConfig

ARTIFACTS_DIR = project_root / "artifacts"

config = IngestionConfig(
    hotpot_file_path=str(ARTIFACTS_DIR / "hotpot_dev_distractor_v1.json"),
    storage_map_path=str(ARTIFACTS_DIR / "file_to_storage_info.json"),
    output_dir=str(ARTIFACTS_DIR),
)

manager = IngestionManager(config)
artifact_paths = manager.ingest()

print("\n[INFO] Generated artifacts:")
for name, path in artifact_paths.items():
    print(f"  - {name}: {path}")
