$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

$Programs = @(
    "tcp_zmq_bridge.py",
    "5_final_fusion.py",
    "ai_decision_dashboard.py",
    "6_turret_server.py"
)

foreach ($Program in $Programs) {
    $Command = "Set-Location -LiteralPath '$Root'; py -3.11 '.\$Program'"

    Start-Process `
        powershell.exe `
        -ArgumentList "-NoExit", "-Command", $Command

    Start-Sleep -Milliseconds 600
}
