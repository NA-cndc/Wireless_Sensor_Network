from pathlib import Path
import hashlib
import json
import shutil
import zipfile
ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT.parent / 'WSN_Security_Update_20261117'
APPLY = 'param(\n    [string]$Project = \'F:\\bangdzaihjhj\\dancctt\',\n    [switch]$CheckOnly\n)\n$ErrorActionPreference = \'Stop\'\n$root = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Project).Path).TrimEnd(\'\\\')\n$bundle = $PSScriptRoot\n$manifest = Get-Content -LiteralPath (Join-Path $bundle \'update_manifest.json\') -Raw -Encoding UTF8 | ConvertFrom-Json\nfunction Inside([string]$base, [string]$relative) {\n    if ([IO.Path]::IsPathRooted($relative)) { throw "Absolute payload path rejected: $relative" }\n    $target = [IO.Path]::GetFullPath((Join-Path $base $relative))\n    if (!$target.StartsWith($base.TrimEnd(\'\\\') + \'\\\', [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes target: $relative" }\n    return $target\n}\n$payloadRoot = [IO.Path]::GetFullPath((Join-Path $bundle \'project\'))\n$updates = @{}\nforeach ($item in $manifest.files) { $updates[$item.path] = $item.sha256 }\n$sourceFiles = @(Get-ChildItem -LiteralPath $root -File -Filter \'*.py\')\nforeach ($folder in @(\'src\',\'scripts\')) {\n    $sourceFolder = Join-Path $root $folder\n    if (Test-Path -LiteralPath $sourceFolder) { $sourceFiles += @(Get-ChildItem -LiteralPath $sourceFolder -File -Filter \'*.py\' -Recurse) }\n}\nforeach ($sourceFile in $sourceFiles) {\n    $relative = $sourceFile.FullName.Substring($root.Length + 1).Replace([char]92, [char]47)\n    if ($relative -notin $manifest.source_before.PSObject.Properties.Name -and !$updates.ContainsKey($relative)) {\n        throw "Additional core source found: $relative. No files were written."\n    }\n}\nforeach ($entry in $manifest.source_before.PSObject.Properties) {\n    $target = Inside $root $entry.Name\n    if (!(Test-Path -LiteralPath $target -PathType Leaf)) { throw "Required source missing: $($entry.Name)" }\n    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()\n    if ($actual -ne $entry.Value -and (!$updates.ContainsKey($entry.Name) -or $actual -ne $updates[$entry.Name])) {\n        throw "Source changed since review: $($entry.Name). No files were written."\n    }\n}\n$pending = @()\nforeach ($item in $manifest.files) {\n    $source = Inside $payloadRoot $item.path\n    $target = Inside $root $item.path\n    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw "Payload hash mismatch: $($item.path)" }\n    if (Test-Path -LiteralPath $target) {\n        if (!(Test-Path -LiteralPath $target -PathType Leaf)) { throw "Target is not a file: $($item.path)" }\n        $current = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()\n        if ($current -eq $item.sha256) { continue }\n        if (!$item.before_sha256 -or $current -ne $item.before_sha256) { throw "Conflicting target: $($item.path). No files were written." }\n    } elseif ($item.before_sha256) { throw "Expected existing file missing: $($item.path)" }\n    $pending += $item\n}\nWrite-Output "Verified payload and source. Pending files: $($pending.Count). Project: $root"\nif ($CheckOnly -or $pending.Count -eq 0) { return }\n$backupRoot = Inside $root (\'results\\security_update_backups\\\' + (Get-Date -Format \'yyyyMMdd_HHmmss_fff\'))\nNew-Item -ItemType Directory -Path $backupRoot -Force | Out-Null\n$applied = @()\nforeach ($item in $pending) {\n    $target = Inside $root $item.path\n    if (Test-Path -LiteralPath $target) {\n        $backup = Inside $backupRoot $item.path\n        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null\n        Copy-Item -LiteralPath $target -Destination $backup -Force\n    }\n    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null\n    Copy-Item -LiteralPath (Inside $payloadRoot $item.path) -Destination $target -Force\n    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw "Post-copy hash mismatch: $($item.path). Backup: $backupRoot" }\n    $applied += $item.path\n}\n@{applied_at=(Get-Date -Format o); project=$root; files=$applied; backup=$backupRoot} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backupRoot \'applied.json\') -Encoding UTF8\nWrite-Output "Applied $($applied.Count) files. Existing files backed up at: $backupRoot"\nWrite-Output "No git commit, push, reset, clean, or delete was performed."\n'
APPLY = APPLY.replace(chr(92) * 2, chr(92))

def main():
    if DEST.exists():
        raise FileExistsError('Do not overwrite an earlier handoff package')
    DEST.mkdir()
    original = zipfile.ZipFile(ROOT / 'evidence/baseline/original_source.zip')
    before_files = original.namelist()
    modified = ['src/wsn_sim/calibration.py', 'README.md', 'RUN_GUIDE.md', 'configs/README.md', 'docs/security_crosscheck_20261117.md', 'tests/test_long_horizon_audit.py', 'configs/detector_long_horizon_20261117.json', 'configs/detector_long_horizon_20261117.lock.json']
    modified += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'analysis/security_audit').glob('*.py')]
    out = ROOT / 'results/security_audit'
    for p in out.rglob('*'):
        if p.is_file() and p.suffix not in {'.jsonl'}:
            modified.append(p.relative_to(ROOT).as_posix())
    modified += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'evidence/baseline').rglob('*') if p.is_file()]
    modified += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'evidence').glob('*.txt')]
    if (ROOT / 'evidence/final_tests.xml').exists():
        modified.append('evidence/final_tests.xml')
    manifest = []
    for name in sorted(set(modified)):
        p = ROOT / name
        dest = DEST / 'project' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        manifest.append({'path': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'before_sha256': hashlib.sha256(original.read(name)).hexdigest() if name in before_files else None})
    old_lock = json.loads(original.read('configs/detector_stage78.lock.json'))
    (DEST / 'update_manifest.json').write_text(json.dumps({'source_before': old_lock['source_fingerprint']['files'], 'source_before_sha256': old_lock['source_fingerprint']['sha256'], 'files': manifest, 'raw_diagnostic_jsonl_omitted_from_portable_package': True, 'raw_diagnostic_jsonl_original_location': str(out / 'diagnostic_old_SF3/ch_0.01/seed_51001'), 'portable_evidence': 'diagnosis.json + representative_full_packet_traces.json + timeout_causes.csv + first FP windows + raw compact fit projections'}, indent=2), encoding='utf-8')
    (DEST / 'Apply-WSNSecurityUpdate.ps1').write_text(APPLY, encoding='utf-8-sig')
    (DEST / 'READ_ME_FIRST.txt').write_text("Ban va da kiem thu trong ban sao. Du an F: chua bi thay doi.\nKiem tra truoc: .\\Apply-WSNSecurityUpdate.ps1 -Project 'F:\\bangdzaihjhj\\dancctt' -CheckOnly\nAp dung: .\\Apply-WSNSecurityUpdate.ps1 -Project 'F:\\bangdzaihjhj\\dancctt'\nScript kiem tra hash tat ca source, sao luu file cu, chi chep cac file trong manifest. Khong xoa du lieu hoac thay doi Git.\nBao cao: project\\docs\\security_crosscheck_20261117.md\nNeu preflight bao conflict, khong ep ghi de; can doi chieu thay doi moi.\n", encoding='utf-8')
    archive = DEST.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in DEST.rglob('*'):
            if p.is_file():
                z.write(p, p.relative_to(DEST))
    print(json.dumps({'package': str(archive), 'size_bytes': archive.stat().st_size, 'files': len(manifest)}))
if __name__ == '__main__':
    main()
