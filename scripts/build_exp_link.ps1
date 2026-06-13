# build_exp_link.ps1 -- experiment measurement-link diagrams (Visio).
#
# Rebuilds figs/fig_exp_mzm.{vsdx,pdf} and figs/fig_exp_dpmzm.{vsdx,pdf} by
# reusing the photonics device shapes from the user's stencil with Visio COM.
# These two figures do NOT come from make_figs.py (they are Visio, not
# matplotlib); the paper \includegraphics the exported PDFs.
#
# Requires: Microsoft Visio installed; the device stencil below.
#   PS> pwsh -File scripts/build_exp_link.ps1
#
# Device shapes used (top-level shape IDs on page 1 of the stencil), found by
# exporting the stencil page and matching icons:
#   549 = LD (red-triangle laser diode)   300 = single MZM
#   611 = DPMZM (dual-parallel: MZMa/MZMb sub + MZMc parent)
#    42 = OC (1:9 fibre coupler, oval)     368 = PP-10G amplified PD
# Fonts: 宋体=5 (boxes/labels, matches the reference), Times New Roman=23.

$ErrorActionPreference = 'Stop'
$stencil = "C:\Users\ckdfs\Downloads\器件visio.vsdx"
$base = Split-Path -Parent $PSScriptRoot   # repo root
$app = New-Object -ComObject Visio.Application; $app.Visible = $false; $app.AlertResponse = 7

function Build($app, $src, $base, $modID, $modW, $modH, $biasXs, $dgLabel, $note, $outBase) {
  $srcDoc = $app.Documents.Open($src); $sp = $srcDoc.Pages.Item(1)
  $doc = $app.Documents.Add(""); $pg = $doc.Pages.Item(1)
  $pg.PageSheet.CellsU("PageWidth").FormulaU = "11.5 in"; $pg.PageSheet.CellsU("PageHeight").FormulaU = "5.6 in"
  $song = "5"; $tnr = "23"; $cyan = "RGB(0,176,240)"; $bk = "RGB(0,0,0)"
  function D($id, $cx, $cy, $w, $h) { $n = $pg.Drop($sp.Shapes.ItemFromID($id), $cx, $cy); $n.CellsU("Width").FormulaU = "$w in"; $n.CellsU("Height").FormulaU = "$h in"; $n }
  function B($cx, $cy, $w, $h, $t, $f) { $r = $pg.DrawRectangle($cx-$w/2, $cy-$h/2, $cx+$w/2, $cy+$h/2); $r.CellsU("Rounding").FormulaU = "0.08 in"; $r.CellsU("LineWeight").FormulaU = "1.2 pt"; $r.CellsU("FillForegnd").FormulaU = "RGB(255,255,255)"; $r.Text = $t; $r.CellsU("Char.Font").FormulaU = $f; $r.CellsU("Char.Size").FormulaU = "11 pt" }
  function L($x1, $y1, $x2, $y2, $c, $d, $a, $w) { $l = $pg.DrawLine($x1, $y1, $x2, $y2); $l.CellsU("LineColor").FormulaU = $c; $l.CellsU("LineWeight").FormulaU = "$w pt"; if ($d) { $l.CellsU("LinePattern").FormulaU = $d }; if ($a) { $l.CellsU("EndArrow").FormulaU = "4" } }
  function T($cx, $cy, $t, $f, $s) { $r = $pg.DrawRectangle($cx-0.6, $cy-0.2, $cx+0.6, $cy+0.2); $r.CellsU("LinePattern").FormulaU = "0"; $r.CellsU("FillPattern").FormulaU = "0"; $r.Text = $t; $r.CellsU("Char.Font").FormulaU = $f; $r.CellsU("Char.Size").FormulaU = "$s pt" }
  $mcx = 3.8; $ym = 2.2; $yb = 4.15; $oc = 6.5; $pdx = 8.4
  $mL = $mcx-$modW/2; $mR = $mcx+$modW/2; $mtop = $ym+$modH/2
  # optical row: LD -> modulator -> OC(1:9) -> PD(1) / dump(9)
  D 549 1.1 $ym 1.0 1.0 | Out-Null
  D $modID $mcx $ym $modW $modH | Out-Null
  D 42 $oc $ym 0.85 0.6 | Out-Null
  D 368 $pdx 2.85 0.95 0.95 | Out-Null
  L 1.6 $ym $mL $ym $cyan $null $true 2.2
  L $mR $ym 6.075 $ym $cyan $null $true 2.2
  L 6.93 2.32 7.97 2.72 $cyan $null $true 2.2
  L 6.70 1.97 7.78 1.30 $cyan $null $true 2.2
  T 7.45 2.66 "1" $tnr 12; T 7.05 1.5 "9" $tnr 12; T 8.2 1.12 "dump" $tnr 10
  # control row (compact, just above the modulator): DG922 <- host PC <- scope
  B $mcx $yb 1.7 0.85 $dgLabel $song
  B 6.0 $yb 1.7 0.85 "上位机`n仿射反演 + PI" $song
  B $pdx $yb 1.7 0.85 "SDS824X HD`n示波器 FFT" $song
  L $pdx 3.33 $pdx ($yb-0.425) $bk $null $true 1.6
  L ($pdx-0.85) $yb 6.87 $yb $bk $null $true 1.6
  L 5.15 $yb ($mcx+0.85) $yb $bk $null $true 1.6
  # dashed dither/bias drops into the modulator electrodes
  foreach ($xb in $biasXs) { L $xb ($yb-0.425) $xb $mtop $bk "2" $true 1.4 }
  if ($note) { T 1.75 3.4 $note $song 9 }
  $pg.ResizeToFitContents()
  $doc.SaveAs("$base\figs\$outBase.vsdx")
  $doc.ExportAsFixedFormat(1, "$base\figs\$outBase.pdf", 1, 0)
  $doc.Close(); $srcDoc.Close()
  "wrote figs/$outBase.vsdx + .pdf"
}
try {
  Build $app $stencil $base 300 1.7 1.0 @(3.8) "DG922 Pro`n偏置 + 导频" "" "fig_exp_mzm"
  Build $app $stencil $base 611 2.6 1.05 @(3.2, 3.8, 4.4) "DG922 Pro ×2`n偏置 + 导频" "两台 DG922 Pro`n产生三路导频" "fig_exp_dpmzm"
} finally { $app.Quit() }
