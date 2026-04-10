$procs = Get-Process | Where-Object { $_.ProcessName -match "node" }
if ($procs) {
    $procs | Format-Table Id, ProcessName, StartTime -AutoSize
} else {
    Write-Host "No node processes found"
}