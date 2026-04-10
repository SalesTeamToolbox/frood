Write-Host "Testing Paperclip UI (port 5173)..."
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:5173' -UseBasicParsing -TimeoutSec 5
    Write-Host "UI Status: $($r.StatusCode)"
    Write-Host "UI Content length: $($r.Content.Length)"
} catch {
    Write-Host "UI Error: $($_.Exception.Message)"
}

Write-Host "`nTesting Paperclip API (port 3100)..."
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3100/api/health' -UseBasicParsing -TimeoutSec 5
    Write-Host "API Status: $($r.StatusCode)"
} catch {
    Write-Host "API Error: $($_.Exception.Message)"
}

Write-Host "`nTesting Frood (port 8000)..."
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000' -UseBasicParsing -TimeoutSec 5
    Write-Host "Frood Status: $($r.StatusCode)"
} catch {
    Write-Host "Frood Error: $($_.Exception.Message)"
}