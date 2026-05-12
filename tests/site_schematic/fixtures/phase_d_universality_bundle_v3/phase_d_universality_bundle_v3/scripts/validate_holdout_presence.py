#!/usr/bin/env python3
import csv, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
manifest = ROOT / 'holdout_download_manifest.csv'
rows = []
with manifest.open() as f:
    for row in csv.DictReader(f):
        target = ROOT / row['target_relative_path']
        rows.append({
            'packet_id': row['packet_id'],
            'target': row['target_relative_path'],
            'present': target.exists(),
            'size_bytes': target.stat().st_size if target.exists() else 0,
        })
summary = {
    'registry_packet_count': len(rows),
    'present_count': sum(1 for r in rows if r['present']),
    'missing_count': sum(1 for r in rows if not r['present']),
    'rows': rows,
}
print(json.dumps(summary, indent=2))
