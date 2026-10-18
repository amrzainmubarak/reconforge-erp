#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$BacklogPath = "docs/execution/BACKLOG.yaml",
    [switch]$Json
)

function Read-BacklogStatuses {
    param([string]$Path)
    $lines = Get-Content $Path
    $entries = @{}
    for ($i=0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '^\s*-\s*id:\s*(?<id>[^\s#]+)') {
            $id = $matches.id.Trim()
            $status = $null
            $title = $null
            for ($j=$i+1; $j -lt $lines.Count; $j++) {
                $next = $lines[$j]
                if ($next -match '^\s*-\s*id:\s*') { break }
                if (-not $status -and $next -match '^\s*status:\s*(?<status>[^#\r\n]+)') { $status = $matches.status.Trim() }
                if (-not $title -and $next -match '^\s*title:\s*(?<title>.+)$') { $title = $matches.title.Trim().Trim('"') }
            }
            if ($id -and $status) { $entries[$id] = @{ id=$id; status=$status; title=$title } }
        }
    }
    return $entries
}

$critical = @(
    'E-824','E-1000','E-1001','E-1002','E-1003','E-1004','E-1005',
    'E-884','E-1006','E-1007','P4-FIN-002','P4-CON-001','P4-SCL-001',
    'P4-REL-001','P4-IAM-001','P4-PLAT-001'
)

$backlog = Read-BacklogStatuses -Path $BacklogPath
$rows = @()
foreach ($id in $critical) {
    if ($backlog.ContainsKey($id)) {
        $rows += [PSCustomObject]@{
            id = $id
            status = $backlog[$id].status
            title = if ($backlog[$id].title) { $backlog[$id].title } else { '' }
        }
    }
}

$blocked = $rows | Where-Object { $_.status -eq 'blocked' }
$inProgress = $rows | Where-Object { $_.status -eq 'in_progress' }
$planned = $rows | Where-Object { $_.status -eq 'planned' }
$p0Open = ($rows | Where-Object { $_.id -like 'E-*' -and $_.status -ne 'completed' }).Count

if ($Json) {
    $payload = [ordered]@{
        date = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        total = $rows.Count
        blocked = $blocked.id
        in_progress = $inProgress.id
        planned = $planned.id
        critical_open = ($inProgress + $blocked + $planned).Count
        executive_line = "Open blockers: $($blocked.id -join ', ') | Open in-progress: $($inProgress.id -join ', ') | Planned: $($planned.id -join ', ')"
    }
    $payload | ConvertTo-Json -Depth 6
    return
}

$line = "EXECUTIVE SNAPSHOT: "
if ($blocked.Count -gt 0) { $line += "Gate-A blocker=$($blocked.id -join ','). " }
$line += "Critical open (P0/P1/P4)=$(($inProgress + $blocked + $planned).Count). "
if ($inProgress.Count -gt 0) { $line += "Active: $($inProgress.id -join ', '). " }
if ($blocked.Count -eq 0 -and $inProgress.Count -eq 0 -and $planned.Count -eq 0) {
    $line += "No critical slice is currently open."
}

$gateLine = "Go-Readiness posture: "
if ($blocked | Where-Object { $_.id -eq 'E-824' }) {
    $gateLine += "Blocked by Gate A (E-824). "
} else {
    $p0Open = ($rows | Where-Object { $_.id -like 'E-*' -and $_.status -ne 'completed' }).Count
    if ($p0Open -gt 0) { $gateLine += "P0 still open. " } else { $gateLine += "P0 clear. " }
}

Write-Host $line -ForegroundColor Cyan
Write-Host $gateLine -ForegroundColor Yellow
Write-Host "Top priority now: " -NoNewline
if ($blocked.Count -gt 0) {
    Write-Host $blocked[0].id -ForegroundColor Red
} elseif ($inProgress.Count -gt 0) {
    Write-Host $inProgress[0].id -ForegroundColor Yellow
} else {
    Write-Host "No critical blockers." -ForegroundColor Green
}

Write-Host "`nTop pending slice statuses:" -ForegroundColor Gray
$rows | Sort-Object id | ForEach-Object {
    Write-Host ("{0,-11} {1}" -f $_.id, $_.status)
}

Write-Host "`nSuggested one-line executive sentence:" -ForegroundColor Green
if ($blocked.Count -gt 0) {
    Write-Host ("E-824=$($blocked.id -join ','); باقي ${p0Open} من عناصر P0/P1/P4 مفتوحة، والأولوية: تنفيذ إزالة blocker أمني ثم إنعاش E-1000/E-1001.")
} else {
    Write-Host ("P0/P1/P4 open count=$p0Open، الأولوية لانتقال: $($inProgress.id -join ', ').")
}
