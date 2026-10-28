<#
    NOVA AI Video Studio - Benchmark runner (roadmap sections 3, 6)
    Runs the Python baseline benchmark suite and writes a JSON report.
    Run:  powershell -ExecutionPolicy Bypass -File scripts\benchmark.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
$py = if (Test-Path $venvPy) { $venvPy } else { 'python' }

Write-Host 'Running NOVA baseline benchmark suite (render always; AI benchmarks'
Write-Host 'skip cleanly when their models are absent)...'

& $py -c @"
import json, sys
sys.path.insert(0, r'$($root)\src')
from nova_studio.core.benchmark import run_baseline_suite
results = [r.model_dump() for r in run_baseline_suite(runs=3)]
print(json.dumps(results, indent=2))
"@
