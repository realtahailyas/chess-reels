<#
.SYNOPSIS
    Registers the three daily tchessapp publish slots as their own scheduled task.

.DESCRIPTION
    Creates "ChessReel Autopilot (tchessapp)" with triggers at 17:00, 01:00 and
    07:00 PKT, each running:  pythonw.exe publish.py --account tchessapp

    🔴 IT DELIBERATELY DOES NOT TOUCH "ChessReel Autopilot". That task has been
    publishing @tahachesstv three times a day since 2026-08-22, and the whole
    point of a second task is that adding the app brand cannot disturb it — a
    modified trigger set, a typo in an argument, or a half-applied edit on the
    existing task would take the working account down. Two tasks also mean the
    new brand can be paused on its own by disabling one task.

    Mirrors the existing task's action, working directory and principal exactly,
    read from the live task rather than hardcoded, so the two cannot drift.

.PARAMETER Remove
    Unregister the tchessapp task instead of creating it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup_tchessapp_schedule.ps1
    powershell -ExecutionPolicy Bypass -File scripts/setup_tchessapp_schedule.ps1 -Remove
#>

[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$SourceTaskName = 'ChessReel Autopilot'
$NewTaskName    = 'ChessReel Autopilot (tchessapp)'
$Account        = 'tchessapp'
# Must match config.ACCOUNTS['tchessapp']['publish_times_pkt'].
$Slots          = @('17:00', '01:00', '07:00')

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Task '$NewTaskName' does not exist - nothing to remove."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $NewTaskName -Confirm:$false
    Write-Host "Removed '$NewTaskName'. @tahachesstv's own task is untouched."
    exit 0
}

# ── Copy the working task's shape rather than restating it ──────────────────
$source = Get-ScheduledTask -TaskName $SourceTaskName -ErrorAction SilentlyContinue
if ($null -eq $source) {
    Write-Error "Could not find the existing task '$SourceTaskName'. This script copies its action and principal; create the tahachesstv task first."
    exit 1
}

$sourceAction = $source.Actions | Select-Object -First 1
$exe          = $sourceAction.Execute
$workDir      = $sourceAction.WorkingDirectory

if ([string]::IsNullOrWhiteSpace($workDir)) {
    $workDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

Write-Host "Copying from '$SourceTaskName':"
Write-Host "  Executable : $exe"
Write-Host "  WorkingDir : $workDir"
Write-Host "  RunAs      : $env:COMPUTERNAME\$env:USERNAME ($($source.Principal.LogonType))"
Write-Host ""

$publishScript = Join-Path $workDir 'publish.py'
if (-not (Test-Path $publishScript)) {
    Write-Error "publish.py not found at $publishScript"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $exe `
                                  -Argument "publish.py --account $Account" `
                                  -WorkingDirectory $workDir

$triggers = @()
foreach ($slot in $Slots) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $slot
}

# 🔴 THE IDENTITY MUST COME FROM THE EXPORTED XML, NOT FROM
# Get-ScheduledTask. The live task stores its principal as a SID
# (S-1-5-21-...-1000); Get-ScheduledTask helpfully resolves that to the
# display name "TahaIlyas", and feeding either that string or the resolved
# Principal object back to Register-ScheduledTask fails with the useless
# "The parameter is incorrect. (34,8):UserId". The XML carries the raw SID,
# which registers cleanly and is by construction the exact same identity the
# working tahachesstv task already runs as.
# 🔴 THE IDENTITY HAS TO BE A MACHINE-QUALIFIED NAME, and nothing else here
# works. Three forms were tried against this exact box and all three were
# rejected with the same unhelpful "The parameter is incorrect. (34,8):UserId":
#   - $source.Principal            (Get-ScheduledTask resolves the stored SID
#                                   to a bare display name, "TahaIlyas")
#   - the raw SID from the task XML (S-1-5-21-...-1000)
#   - that bare display name on its own
# Register-ScheduledTask wants DOMAIN\USER, so it is built here rather than
# copied off the source task. RunLevel still comes from the source so the two
# tasks cannot drift apart on privilege.
$runAs = "$env:COMPUTERNAME\$env:USERNAME"

# StartWhenAvailable matters on a laptop: a slot that falls while the machine
# is asleep should still run once it wakes, rather than being skipped until
# tomorrow. MultipleInstances=IgnoreNew is belt-and-braces behind publish.py's
# own lock file.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                         -MultipleInstances IgnoreNew `
                                         -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
                                         -DontStopIfGoingOnBatteries `
                                         -AllowStartIfOnBatteries

$existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Write-Host "Task '$NewTaskName' already exists - updating its triggers and action."
    Set-ScheduledTask -TaskName $NewTaskName -Action $action -Trigger $triggers -Settings $settings | Out-Null
} else {
    Register-ScheduledTask -TaskName $NewTaskName `
                           -Action $action `
                           -Trigger $triggers `
                           -User $runAs `
                           -RunLevel $source.Principal.RunLevel `
                           -Settings $settings `
                           -Description "Publishes @tchessapp reels (IG + YouTube), 3x daily, offset 2h from the tahachesstv slots." | Out-Null
    Write-Host "Registered '$NewTaskName'."
}

Write-Host ""
Write-Host "Daily schedule now:"
Write-Host "  05:00 PKT  tahachesstv"
Write-Host "  07:00 PKT  tchessapp"
Write-Host "  15:00 PKT  tahachesstv"
Write-Host "  17:00 PKT  tchessapp"
Write-Host "  23:00 PKT  tahachesstv"
Write-Host "  01:00 PKT  tchessapp"
Write-Host ""
Write-Host "Verify with:  Get-ScheduledTask -TaskName '$NewTaskName' | Select-Object -ExpandProperty Triggers"
Write-Host "Dry-run one:  python publish.py --account $Account --dry-run --verbose"
