#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$BacklogPath = "docs/execution/BACKLOG.yaml",
    [string]$ClaimsPath = "docs/execution/CLAIMS_EVIDENCE_MATRIX.md",
    [string[]]$CriticalIds = @(
        "E-824","E-1000","E-1001","E-1002","E-1003","E-1004","E-1005",
        "E-884","E-1006","E-1007","P4-FIN-002","P4-CON-001","P4-SCL-001",
        "P4-REL-001","P4-IAM-001","P4-PLAT-001"
    )
)

function Get-BacklogStatus {
    param([string]$Path,[string[]]$CriticalIds)
    $lines = Get-Content $Path
    $entries = @{}

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '^\s*-\s*id:\s*(?<id>[^\s#]+)') {
            $id = $matches.id.Trim()
            $status = $null
            $title = $null
            for ($j = $i + 1; $j -lt $lines.Count; $j++) {
                $next = $lines[$j]
                if ($next -match '^\s*-\s*id:\s*') { break }
                if ($next -match '^\s*status:\s*(?<st>[A-Za-z_]+)' -and -not $status) {
                    $status = $matches.st.Trim()
                }
                if ($next -match '^\s*title:\s*(?<tt>.+)$' -and -not $title) {
                    $title = $matches.tt.Trim().Trim('"')
                }
            }
            if ($CriticalIds -contains $id) {
                $entries[$id] = @{
                    id = $id
                    status = $status
                    title = $title
                }
            }
        }
    }
    return $entries
}

function Find-ClaimDriftHints {
    param([string]$ClaimsPath,[string[]]$CriticalIds)
    $text = Get-Content $ClaimsPath -Raw
    $results = @()
    $flagWords = 'global|production|enterprise|hosted|capacity|HA/DR|ha-dr|provider|compliance|certified|certification|banking|bank|regulated'

    foreach ($id in $CriticalIds) {
        if ($text -notmatch [regex]::Escape($id)) { continue }
        $lines = Get-Content $ClaimsPath
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match [regex]::Escape($id)) {
                $windowStart = [Math]::Max(0, $i - 1)
                $windowEnd = [Math]::Min($lines.Count - 1, $i + 2)
                $window = ($lines[$windowStart..$windowEnd] -join " ")
                if ($window -match $flagWords -and $window -notmatch 'not|bounded|local-first|local|experimental|bound') {
                    $results += [PSCustomObject]@{
                        Id = $id
                        Line = $i + 1
                        Segment = $window.Trim()
                    }
                }
            }
        }
    }
    return $results
}

$backlog = Get-BacklogStatus -Path $BacklogPath -CriticalIds $CriticalIds
$drift = Find-ClaimDriftHints -ClaimsPath $ClaimsPath -CriticalIds $CriticalIds

Write-Host "=== GLOBAL PROFESSIONAL FAST CHECK ===" -ForegroundColor Cyan
Write-Host "Backlog: $BacklogPath"
Write-Host "Claims: $ClaimsPath"
Write-Host ""

$blocked = @()
$inProgress = @()
$other = @()
foreach ($entry in $backlog.GetEnumerator()) {
    $id = $entry.Key
    $status = $entry.Value.status
    $title = $entry.Value.title
    if ($null -eq $status) { $status = "unknown"; $other += "$id"; continue }
    switch ($status) {
        "blocked" { $blocked += "$id" }
        "in_progress" { $inProgress += "$id" }
        default { }
    }
}

Write-Host "Critical slice snapshot" -ForegroundColor Yellow
foreach ($id in $CriticalIds) {
    if ($backlog.ContainsKey($id)) {
        $s = $backlog[$id]
        Write-Host ("{0,-11} {1,-11} {2}" -f $s.id,$s.status,$s.title)
    }
}

if ($blocked.Count -gt 0) {
    Write-Host ""
    Write-Host "Blocking IDs (P0/P1/P4 that are blocked):" -ForegroundColor Red
    $blocked | ForEach-Object { Write-Host (" - $_") }
}

if ($inProgress.Count -gt 0) {
    Write-Host ""
    Write-Host "Open in-progress IDs:" -ForegroundColor Yellow
    $inProgress | ForEach-Object { Write-Host (" - $_") }
}

if ($drift.Count -gt 0) {
    Write-Host ""
    Write-Host "⚠️  Potential claim-drift candidates (manual review):" -ForegroundColor Magenta
    $drift | ForEach-Object {
        Write-Host (" - {0} @ line {1}" -f $_.Id, $_.Line)
        Write-Host ("   {0}" -f ($_.Segment))
    }
} else {
    Write-Host ""
    Write-Host "No additional claim-drift candidates detected by heuristic (manual review still required)." -ForegroundColor Green
}

if ($blocked.Count -gt 0 -and $blocked -contains "E-824") {
    Write-Host ""
    Write-Host "Gate A still blocked: E-824 is blocked." -ForegroundColor Red
}

Write-Host ""
Write-Host "Decision reminder:"
Write-Host "  - No Go claim if E-824 != completed."
Write-Host "  - No Go-Ready if any critical P0 remains blocked or in_progress."
Write-Host "  - Any high-impact wording must remain bounded/local-first unless evidence is complete."
