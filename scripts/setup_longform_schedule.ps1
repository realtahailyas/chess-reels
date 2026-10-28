<#
.SYNOPSIS
    Registers the long-form YouTube autopilot as its own scheduled task.

.DESCRIPTION
    Creates "ChessReel Longform", which runs  pythonw.exe longform_daily.py
    at 04:00 and 16:00 local time (PKT). The 04:00 run does the heavy
    work (engine + render) while the laptop is normally idle; the 16:00 run is a
    backup that usually only has nothing, or an upload, to do.

    Neither run publishes anything at that moment. Each run renders what is
    missing and uploads it PRIVATE with a publishAt time, and YouTube flips it
    public at the channel's slot:
        Taha Chess  12:00 New York  (21:00 PKT, 22:00 in winter)
        TChess      17:30 New York  (02:30 PKT, 03:30 in winter)
    Two runs a day, each scheduling up to two days ahead, so one missed run
    (laptop asleep, no network) costs nothing.

    🔴 IT DOES NOT TOUCH THE SHORTS TASKS ("ChessReel Autopilot" and
    "ChessReel Autopilot (tchessapp)"). It only reads the first one to copy its
    python executable, working directory and run level.

.PARAMETER Remove
    Unregister the long-form task instead of creating it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup_longform_schedule.ps1
    powershell -ExecutionPolicy Bypass -File scripts/setup_longform_schedule.ps1 -Remove
#>

[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$SourceTaskName = 'ChessReel Autopilot'
$NewTaskName    = 'ChessReel Longform'
$Runs           = @('04:00', '16:00')

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Task '$NewTaskName' does not exist - nothing to remove."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $NewTaskName -Confirm:$false
    Write-Host "Removed '$NewTaskName'. The shorts tasks are untouched."
    exit 0
}

$source = Get-ScheduledTask -TaskName $SourceTaskName -ErrorAction SilentlyContinue
if ($null -eq $source) {
    Write-Error "Could not find '$SourceTaskName' to copy the python executable from."
    exit 1
}
$sourceAction = $source.Actions | Select-Object -First 1
$exe     = $sourceAction.Execute
$workDir = $sourceAction.WorkingDirectory
if ([string]::IsNullOrWhiteSpace($workDir)) {
    $workDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
if (-not (Test-Path (Join-Path $workDir 'longform_daily.py'))) {
    Write-Error "longform_daily.py not found in $workDir"
    exit 1
}

Write-Host "Executable : $exe"
Write-Host "WorkingDir : $workDir"

$action   = New-ScheduledTaskAction -Execute $exe -Argument 'longform_daily.py' -WorkingDirectory $workDir
$triggers = @()
foreach ($t in $Runs) { $triggers += New-ScheduledTaskTrigger -Daily -At $t }

# Rendering and the engine take up to ~40 min when two videos are due at once,
# so the limit is generous. StartWhenAvailable catches a run missed in sleep.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                         -WakeToRun `
                                         -MultipleInstances IgnoreNew `
                                         -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
                                         -DontStopIfGoingOnBatteries `
                                         -AllowStartIfOnBatteries

# Same identity rule as setup_tchessapp_schedule.ps1: Register-ScheduledTask
# only accepts a machine-qualified DOMAIN\USER here.
$runAs = "$env:COMPUTERNAME\$env:USERNAME"

$existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Set-ScheduledTask -TaskName $NewTaskName -Action $action -Trigger $triggers -Settings $settings | Out-Null
    Write-Host "Updated '$NewTaskName'."
} else {
    Register-ScheduledTask -TaskName $NewTaskName -Action $action -Trigger $triggers `
                           -User $runAs -RunLevel $source.Principal.RunLevel -Settings $settings `
                           -Description 'Renders and schedules the long-form GM game videos on Taha Chess and TChess (YouTube).' | Out-Null
    Write-Host "Registered '$NewTaskName'."
}
Write-Host "Runs daily at $($Runs -join ' and ') local time."
