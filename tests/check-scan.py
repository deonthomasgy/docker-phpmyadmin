#!/usr/bin/env python3
"""Fail when a requested RCE or any fixable finding remains. No ignore lists."""
import collections
import json
import sys

requested = {
    'CVE-2026-46633', 'CVE-2025-15467', 'CVE-2025-68263',
    'CVE-2026-23918', 'CVE-2026-28387', 'CVE-2026-28780',
    'CVE-2026-63292', 'CVE-2026-64396', 'CVE-2026-86145',
}
report = json.load(open(sys.argv[1]))
findings = [v for r in report.get('Results', []) for v in r.get('Vulnerabilities', [])]
remaining = sorted({v['VulnerabilityID'] for v in findings} & requested)
fixable = [v for v in findings if v.get('FixedVersion')]
summary = {
    'image': report['ArtifactName'],
    'counts': dict(collections.Counter(v['Severity'] for v in findings)),
    'requested_rce_remaining': remaining,
    'findings_with_fixed_versions': len(fixable),
    'remaining_critical_high': [
        {k: v.get(k, '') for k in ('VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity', 'Title')}
        for v in findings if v['Severity'] in ('CRITICAL', 'HIGH')
    ],
}
print(json.dumps(summary, indent=2))
if remaining or fixable:
    sys.exit('Security gate failed: requested RCEs or fixable vulnerabilities remain')
