import json
from pathlib import Path
import subprocess
import sys
import pandas as pd

def test_demo_generates_all_required_outputs(project_root: Path) -> None:
    result = subprocess.run([sys.executable, 'scripts/run_demo.py'], cwd=project_root, check=True, capture_output=True, text=True)
    output = Path(next((line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('output_directory='))))
    csv_path = output / 'topology_summary.csv'
    manifest_path = output / 'run_manifest.json'
    figure_paths = [output / 'figures' / f'topology_R{radius}.png' for radius in (250, 300, 350)]
    assert 'sensors=450' in result.stdout
    assert 'sinks=7' in result.stdout
    assert csv_path.exists()
    assert len(pd.read_csv(csv_path)) == 3
    assert all((path.exists() and path.stat().st_size > 0 for path in figure_paths))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['seed'] == 42
    assert len(manifest['generated_files']) == 5
