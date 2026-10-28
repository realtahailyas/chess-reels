<#
.SYNOPSIS
    Registers the long-form FACEBOOK reel poster as its own scheduled task.

.DESCRIPTION
    Creates "ChessReel Longform FB", which runs
        pythonw.exe longform_daily.py --facebook
    at 05:30 and 06:20 local time (PKT).

    05:30 PKT = 20:30 New York (19:30 in winter), US prime time. The reel is
    rendered in advance by the 04:00 "ChessReel Longform" run, so this task
    only posts. The Meta composer posts live, so the task time IS the slot.

    06:20 is a retry trigger. longform/facebook.py posts at most one reel per
    PKT day, so the second trigger does nothing once 05:30 has succeeded.

    Both triggers stay clear of the shorts' Facebook posts on the same Chrome
    profile (about xx:02-xx:06 around 05:00 and 07:00). If the shorts
    autopilot still holds publish.lock, the poster waits for it.

    🔴 IT DOES NOT TOUCH ANY OTHER TASK. It only reads "ChessReel Autopilot" to
    copy its python executable, working directory and run level.

.PARAMETER Remove
    Unregister the task.
#>

[CmdletBinding()]
param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$SourceTaskName = 'ChessReel Autopilot'
$NewTaskName    = 'ChessReel Longform FB'
$Runs           = @('05:30', '06:20')   # must match lfconfig.FACEBOOK slot_pkt / retry_pkt

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Task '$NewTaskName' does not exist - nothing to remove."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $NewTaskName -Confirm:$false
    Write-Host "Removed '$NewTaskName'. Every other task is untouched."
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

$action   = New-ScheduledTaskAction -Execute $exe -Argument 'longform_daily.py --facebook' -WorkingDirectory $workDir
$triggers = @()
foreach ($t in $Runs) { $triggers += New-ScheduledTaskTrigger -Daily -At $t }

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                         -WakeToRun `
                                         -MultipleInstances IgnoreNew `
                                         -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
                                         -DontStopIfGoingOnBatteries `
                                         -AllowStartIfOnBatteries

$runAs = "$env:COMPUTERNAME\$env:USERNAME"

$existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Set-ScheduledTask -TaskName $NewTaskName -Action $action -Trigger $triggers -Settings $settings | Out-Null
    Write-Host "Updated '$NewTaskName'."
} else {
    Register-ScheduledTask -TaskName $NewTaskName -Action $action -Trigger $triggers `
                           -User $runAs -RunLevel $source.Principal.RunLevel -Settings $settings `
                           -Description 'Posts the daily 9:16 long-form GM game reel to the Taha Chess TV Facebook Page.' | Out-Null
    Write-Host "Registered '$NewTaskName'."
}
Write-Host "Runs daily at $($Runs -join ' and ') local time."
