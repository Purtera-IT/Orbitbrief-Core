#!/usr/bin/env python3
import csv, os, sys, requests
from pathlib import Path
MANIFEST = Path(__file__).resolve().parents[1] / 'holdout_download_manifest.csv'
ROOT = Path(__file__).resolve().parents[1]
outcomes = []
with MANIFEST.open() as f:
    reader = csv.DictReader(f)
    for row in reader:
        url = row['url']
        target = ROOT / row['target_relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        status = 'downloaded'
        detail = ''
        try:
            r = requests.get(url, stream=True, timeout=60, headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status()
            with target.open('wb') as out:
                for chunk in r.iter_content(1024*64):
                    if chunk:
                        out.write(chunk)
        except Exception as e:
            status = 'failed'
            detail = str(e)
        outcomes.append({'packet_id':row['packet_id'],'target':str(target),'status':status,'detail':detail})
print('packet_id,status,target,detail')
for o in outcomes:
    print(f"{o['packet_id']},{o['status']},{o['target']},{o['detail']}")
if any(o['status']!='downloaded' for o in outcomes):
    sys.exit(1)
