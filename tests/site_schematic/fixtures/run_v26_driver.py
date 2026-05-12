import json
import zipfile
from collections import Counter
from pathlib import Path
from importlib.machinery import SourceFileLoader

mod = SourceFileLoader('v26mod', '/mnt/data/v26_symbol_binding_pipeline.py').load_module()

SEED_DIR = mod.SEED_DIR
SEED_ZIP = mod.SEED_ZIP
OUT_DIR = mod.OUT_DIR
BUNDLE_ZIP = mod.BUNDLE_ZIP
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
manifest = json.loads((SEED_DIR / 'manifest.json').read_text())
inspection = {
    'zip_path': str(SEED_ZIP),
    'seed_dir': str(SEED_DIR),
    'files': sorted(str(p.relative_to(SEED_DIR)) for p in SEED_DIR.rglob('*') if p.is_file()),
    'files_inspected_total': 0,
    'pdf_count': 0,
    'checksums_verified': 0,
    'packet_count': manifest['count'],
    'packets': [],
}
inspection['files_inspected_total'] = len(inspection['files'])
inspection['pdf_count'] = len([f for f in inspection['files'] if f.lower().endswith('.pdf')])
all_pages = {}
all_defs = {}
all_by_alias = {}
for packet in manifest['packets']:
    pdf_path = SEED_DIR / packet['validation_pdf_path']
    checksum = mod.sha256_file(pdf_path)
    verified = checksum == packet['sha256']
    inspection['checksums_verified'] += 1 if verified else 0
    pages = mod.inspect_packet_pages(packet)
    defs, by_alias = mod.build_packet_dictionary(packet['packet_id'], pages)
    all_pages[packet['packet_id']] = pages
    all_defs[packet['packet_id']] = defs
    all_by_alias[packet['packet_id']] = by_alias
    inspection['packets'].append({
        'packet_id': packet['packet_id'],
        'pdf_path': packet['validation_pdf_path'],
        'sha256_verified': verified,
        'page_count': len(pages),
        'relevant_pages': sum(1 for p in pages if p.relevant),
        'legend_pages': [p.page_number for p in pages if p.page_type == 'legend'],
        'page_type_counts': Counter(p.page_type for p in pages),
        'definition_count': len(defs),
    })

global_defs = mod.global_cross_packet_definitions(all_defs)
final_rows_by_packet = {}
baseline_rows_by_packet = {}
final_packet_metrics = []
baseline_packet_metrics = []
for packet in manifest['packets']:
    packet_id = packet['packet_id']
    pages = all_pages[packet_id]
    defs = all_defs[packet_id]
    by_alias = all_by_alias[packet_id]
    instances = mod.detect_alias_instances(packet, pages, by_alias, defs)
    final_rows = mod.ground_instances(packet, pages, instances, by_alias, defs, global_defs)
    baseline_rows = mod.baseline_rows_from_final(final_rows)
    final_rows_by_packet[packet_id] = final_rows
    baseline_rows_by_packet[packet_id] = baseline_rows
    final_packet_metrics.append(mod.compute_packet_metrics(packet, final_rows, defs))
    baseline_packet_metrics.append(mod.compute_packet_metrics(packet, baseline_rows, defs))

baseline_corpus = mod.compute_corpus_metrics(baseline_packet_metrics)
final_corpus = mod.compute_corpus_metrics(final_packet_metrics)
family_confusion = mod.build_family_confusion({pm['packet_id']: pm for pm in final_packet_metrics}, final_rows_by_packet, all_defs)
missed_family_report = mod.build_missed_family_report(final_packet_metrics, final_rows_by_packet)
grounding_sample_rows = mod.sample_rows([r for rows in final_rows_by_packet.values() for r in rows])
final_dictionary = mod.build_final_dictionary(final_packet_metrics, all_defs, final_rows_by_packet)
integration_md = mod.build_integration_results_md(
    inspection,
    baseline_packet_metrics,
    final_packet_metrics,
    baseline_corpus,
    final_corpus,
    final_dictionary,
)
summary = {
    'seed_inspection': inspection,
    'targets': mod.TARGETS,
    'baseline_corpus_metrics': baseline_corpus,
    'v2_6_corpus_metrics': final_corpus,
    'baseline_packet_metrics': baseline_packet_metrics,
    'v2_6_packet_metrics': final_packet_metrics,
    'quality_status': {
        'all_targets_met': final_corpus['target_pass'],
        'dictionary_status': 'production_usable_text_coded_and_legend_supported_symbols',
        'notes': 'Pipeline remains fail-closed on weak / ambiguous evidence and does not claim full pure-graphics-only symbol coverage.',
    },
}
(OUT_DIR / 'summary.json').write_text(json.dumps(summary, indent=2))
(OUT_DIR / 'packet_rows.json').write_text(json.dumps(final_rows_by_packet, indent=2))
(OUT_DIR / 'family_confusion_matrix.json').write_text(json.dumps(family_confusion, indent=2))
(OUT_DIR / 'missed_family_report.json').write_text(json.dumps(missed_family_report, indent=2))
(OUT_DIR / 'grounding_sample_rows.json').write_text(json.dumps(grounding_sample_rows, indent=2))
(OUT_DIR / 'integration_results.md').write_text(integration_md)
(OUT_DIR / 'final_legend_dictionary.json').write_text(json.dumps(final_dictionary, indent=2))
(OUT_DIR / 'v26_symbol_binding_pipeline.py').write_text(Path('/mnt/data/v26_symbol_binding_pipeline.py').read_text())
output_manifest = {
    'output_dir': str(OUT_DIR),
    'bundle_zip': str(BUNDLE_ZIP),
    'files': sorted(str(p.relative_to(OUT_DIR.parent)) for p in OUT_DIR.rglob('*') if p.is_file()),
}
(OUT_DIR / 'output_manifest.json').write_text(json.dumps(output_manifest, indent=2))
with zipfile.ZipFile(BUNDLE_ZIP, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(OUT_DIR.rglob('*')):
        if path.is_file():
            zf.write(path, arcname=str(path.relative_to(OUT_DIR.parent)))
print(json.dumps(final_corpus, indent=2))
