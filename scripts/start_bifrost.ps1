# Starts the Bifrost gateway on http://localhost:8090 using bifrost/config.json.
# Provider keys are read from .env so they never live in the config file.

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"

if (-not (Test-Path $envFile)) {
    Write-Error "Missing .env. Copy .env.example to .env and fill in your keys."
    exit 1
}

foreach ($line in Get-Content $envFile) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $name, $value = $trimmed -split "=", 2
    if ($null -ne $value) {
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
}

foreach ($required in @("GROQ_API_KEY", "GEMINI_API_KEY", "BIFROST_VIRTUAL_KEY", "BIFROST_SETUP_TOKEN")) {
    if (-not [Environment]::GetEnvironmentVariable($required, "Process")) {
        Write-Error "$required is empty in .env"
        exit 1
    }
}

npx -y @maximhq/bifrost -app-dir (Join-Path $root "bifrost") -port 8090 -log-style pretty
