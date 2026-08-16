#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Set the project version everywhere it is declared, in one step.

.DESCRIPTION
    The version lives in four places across three files, and two of them are
    easy to miss by hand: backend/src/__init__.py states it twice (a docstring
    and the __version__ the running app actually reports), and
    frontend/package-lock.json states it twice as well (the top-level field and
    packages[""].version). A partial bump is silent -- the app keeps reporting
    the old version from /health and the startup log while every other file
    says otherwise.

    The lockfile is the one that punishes a find-and-replace. It legitimately
    contains the project's own version string in unrelated places: a dependency
    range such as "ast-kit": "^2.1.2", and any package that happens to sit at
    the same version, as xmlhttprequest-ssl did at 2.1.2. Only the two fields
    anchored to "name": "frontend" belong to this project.

    Each target is matched structurally, by its key, rather than by replacing
    the old version string. That means the script is safe to run against a tree
    that is already half-bumped, which is the state a hand edit tends to leave.

    CHANGELOG.md and SUMMARY-OF-CHANGES.md are deliberately NOT touched. They
    are historical records with one section per release; rewriting version
    strings in them would corrupt the entries for past releases.

.PARAMETER Version
    The version to set, e.g. 2.1.3 or 2.2.0. Semver with an optional
    prerelease and build suffix.

.PARAMETER Check
    Report what each file currently declares and exit. Writes nothing.
    Exit code 1 if the declarations disagree.

.EXAMPLE
    ./scripts/bump-version.ps1 -Version 2.1.3

.EXAMPLE
    ./scripts/bump-version.ps1 -Check

.EXAMPLE
    ./scripts/bump-version.ps1 -Version 2.2.0 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Set')]
param(
    [Parameter(Mandatory, Position = 0, ParameterSetName = 'Set')]
    [string]$Version,

    [Parameter(Mandatory, ParameterSetName = 'Check')]
    [switch]$Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot

# Semver, with the prerelease and build parts this project actually uses.
$SemVerPattern = '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'

# Every declaration, matched by its key. `Pattern` must capture the text before
# the version as group 1 and the text after as group 2, so the replacement can
# rebuild the line without assuming anything about the current value.
#
# The 3.0 line also declares the version in pyproject.toml. That file does not
# exist on 2.x, which packages the backend from requirements.txt, so the target
# is absent here rather than optional: Get-Declared throws on a missing file by
# design, so that a layout change is reported instead of silently skipped.
$Targets = @(
    @{
        File    = 'backend/src/__init__.py'
        What    = '__version__ (reported by /health, the startup log and the OpenAPI schema)'
        Pattern = '(?m)^(__version__\s*=\s*")[^"]*(")'
    }
    @{
        File    = 'backend/src/__init__.py'
        What    = 'module docstring'
        Pattern = '(?m)^(Version:\s*)\S+(\s*)$'
    }
    @{
        # Both files declare the root package as `"name": "frontend"` followed
        # by its version. Anchoring to that pair hits the top-level field and
        # packages[""].version in the lockfile, and nothing else -- a bare
        # '"version":' would rewrite every dependency in the lockfile.
        File    = 'frontend/package.json'
        What    = 'package version'
        Pattern = '("name"\s*:\s*"frontend"\s*,\s*[\r\n]+\s*"version"\s*:\s*")[^"]*(")'
    }
    @{
        File    = 'frontend/package-lock.json'
        What    = 'lockfile version (declared twice)'
        Pattern = '("name"\s*:\s*"frontend"\s*,\s*[\r\n]+\s*"version"\s*:\s*")[^"]*(")'
    }
)

function Read-Text([string]$Path) {
    # Raw read/write, so CRLF line endings and the absence of a BOM survive.
    # Anything that normalises newlines here shows up as a whole-file diff.
    return [System.IO.File]::ReadAllText($Path)
}

function Write-Text([string]$Path, [string]$Content) {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Get-Declared([hashtable]$Target) {
    $path = Join-Path $RepoRoot $Target.File
    if (-not (Test-Path $path)) {
        throw "$($Target.File) is missing. The version layout has changed; update $($MyInvocation.MyCommand.Name)."
    }
    $text = Read-Text $path
    $found = [regex]::Matches($text, $Target.Pattern)
    if ($found.Count -eq 0) {
        throw "No '$($Target.What)' declaration found in $($Target.File). The version layout has changed; update this script rather than bumping by hand."
    }
    # A regex whose captures are (prefix)(suffix) puts the value between them.
    $values = foreach ($m in $found) {
        $start = $m.Groups[1].Index + $m.Groups[1].Length
        $length = $m.Groups[2].Index - $start
        $text.Substring($start, $length).Trim()
    }
    return [pscustomobject]@{
        Target = $Target
        Path   = $path
        Text   = $text
        Count  = $found.Count
        Values = @($values)
    }
}

$state = foreach ($t in $Targets) { Get-Declared $t }

# ---- report current state -------------------------------------------------

Write-Host ''
Write-Host 'Current declarations:' -ForegroundColor Cyan
foreach ($s in $state) {
    $shown = ($s.Values | Sort-Object -Unique) -join ', '
    $suffix = if ($s.Count -gt 1) { " ($($s.Count) occurrences)" } else { '' }
    Write-Host ('  {0,-32} {1,-46} {2}{3}' -f $s.Target.File, $s.Target.What, $shown, $suffix)
}

$distinct = @($state.Values | Sort-Object -Unique)

if ($Check) {
    Write-Host ''
    if ($distinct.Count -eq 1) {
        Write-Host "Consistent at $($distinct[0])." -ForegroundColor Green
        exit 0
    }
    Write-Host "INCONSISTENT: $($distinct -join ' vs ')" -ForegroundColor Red
    Write-Host "Run: ./scripts/bump-version.ps1 -Version <version>"
    exit 1
}

# ---- write ----------------------------------------------------------------

if ($Version -notmatch $SemVerPattern) {
    throw "'$Version' is not a valid version. Expected semver, e.g. 2.1.3 or 2.2.0."
}

Write-Host ''
Write-Host "Setting every declaration to $Version" -ForegroundColor Cyan

$changed = 0
$byPath = $state | Group-Object Path

foreach ($group in $byPath) {
    $path = $group.Name
    $text = Read-Text $path
    $original = $text

    foreach ($s in $group.Group) {
        # '$1' and '$2' are the captured prefix/suffix, so whatever the file
        # currently holds is replaced without needing to know what it was.
        $text = [regex]::Replace($text, $s.Target.Pattern, "`${1}$Version`${2}")
    }

    $relative = [System.IO.Path]::GetRelativePath($RepoRoot, $path).Replace('\', '/')

    if ($text -eq $original) {
        Write-Host "  = $relative (already $Version)"
        continue
    }

    if ($PSCmdlet.ShouldProcess($relative, "set version to $Version")) {
        Write-Text $path $text
        Write-Host "  + $relative" -ForegroundColor Green
        $changed++
    }
}

if ($WhatIfPreference) {
    Write-Host ''
    Write-Host 'Dry run, nothing written.' -ForegroundColor Yellow
    exit 0
}

# ---- verify ---------------------------------------------------------------
# The point of the script. A bump that silently misses a declaration is the
# failure it exists to prevent, so re-read from disk rather than trusting the
# writes above.

$after = foreach ($t in $Targets) { Get-Declared $t }
$wrong = @($after | Where-Object { $_.Values | Where-Object { $_ -ne $Version } })

Write-Host ''
if ($wrong.Count -gt 0) {
    Write-Host 'FAILED: these still disagree after writing:' -ForegroundColor Red
    foreach ($w in $wrong) {
        Write-Host "  $($w.Target.File): $($w.Target.What) = $(($w.Values | Sort-Object -Unique) -join ', ')"
    }
    exit 1
}

Write-Host "All declarations now read $Version ($changed file(s) written)." -ForegroundColor Green

# A stray copy elsewhere in the tree is worth knowing about even though this
# script will not touch it. Prose in the changelog and the development log is
# expected to name old versions and is excluded.
#
# The two frontend JSON files are read structurally rather than by substring.
# package-lock.json names third-party versions constantly, and Select-String
# -SimpleMatch is a substring test, so scanning it plainly reports ms@2.1.3,
# obug@2.1.3 and even mime-types@2.1.35 as strays on the 2.1.x line. Only the
# fields anchored to `"name": "frontend"` belong to this project, so keying on
# that anchor keeps both files in the scan while dropping the noise, instead of
# excluding the lockfile and going blind to a genuine second declaration in it.
$FrontendAnchor = '"name"\s*:\s*"frontend"\s*,\s*[\r\n]+\s*"version"\s*:\s*"([^"]*)"'
$StructuralFiles = @('frontend/package.json', 'frontend/package-lock.json')

$previous = @($distinct | Where-Object { $_ -ne $Version })
if ($previous.Count -gt 0) {
    $tracked = & git -C $RepoRoot ls-files 2>$null
    if ($LASTEXITCODE -eq 0) {
        # This script names versions in its own examples and its invalid-version
        # message, which is prose exactly like the changelog. Excluded by
        # computed path so renaming the file cannot quietly reintroduce it.
        $self = [System.IO.Path]::GetRelativePath($RepoRoot, $PSCommandPath).Replace('\', '/')
        $excluded = @('CHANGELOG.md', 'SUMMARY-OF-CHANGES.md', $self)
        $stray = foreach ($file in $tracked) {
            if ($excluded -contains $file) { continue }
            if ($file -like 'tests/artifacts/*') { continue }
            $full = Join-Path $RepoRoot $file
            if (-not (Test-Path $full -PathType Leaf)) { continue }

            $declared = if ($StructuralFiles -contains $file) {
                @([regex]::Matches((Read-Text $full), $FrontendAnchor) |
                    ForEach-Object { $_.Groups[1].Value })
            }
            else { $null }

            foreach ($old in $previous) {
                $hit = if ($null -ne $declared) {
                    $declared -contains $old
                }
                else {
                    Select-String -Path $full -SimpleMatch $old -Quiet -ErrorAction SilentlyContinue
                }
                if ($hit) {
                    "$file (still names $old)"
                    break
                }
            }
        }
        if ($stray) {
            Write-Host ''
            Write-Host 'Note: the previous version is still named in:' -ForegroundColor Yellow
            $stray | ForEach-Object { Write-Host "  $_" }
            Write-Host 'Check whether any of these are declarations this script should own.'
        }
    }
}

Write-Host ''
Write-Host 'Next: review the diff, then commit.' -ForegroundColor Cyan
