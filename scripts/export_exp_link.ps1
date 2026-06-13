# export_exp_link.ps1 -- refresh the experiment-link PDFs from the (hand-edited)
# Visio sources, WITHOUT rebuilding.
#
# Opens figs/fig_exp_{mzm,dpmzm}.vsdx and exports each to the same-named PDF.
# It only READS the .vsdx and writes the .pdf -- your .vsdx edits are never
# touched. Run this after editing the figures in Visio so the paper (which
# \includegraphics the .pdf) picks up your changes.
#
#   PS> pwsh -File scripts/export_exp_link.ps1     (or: make exp-figs)
#
# NOTE: do NOT run build_exp_link.ps1 to refresh -- that one rebuilds both files
# from scratch and OVERWRITES your manual edits. Use it only to start over.

$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot   # repo root
$app = New-Object -ComObject Visio.Application; $app.Visible = $false; $app.AlertResponse = 7
try {
  foreach ($n in 'fig_exp_mzm', 'fig_exp_dpmzm') {
    $vsdx = Join-Path $base "figs\$n.vsdx"
    if (-not (Test-Path $vsdx)) { Write-Warning "missing $vsdx -- skipped"; continue }
    $doc = $app.Documents.Open($vsdx)
    $doc.ExportAsFixedFormat(1, (Join-Path $base "figs\$n.pdf"), 1, 0)  # 1=PDF
    $doc.Close()
    "exported figs/$n.pdf from $n.vsdx"
  }
} finally { $app.Quit() }
