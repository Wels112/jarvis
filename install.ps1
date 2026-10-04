# Установщик Джарвиса. Запуск одной строкой в PowerShell:
#
#   irm https://raw.githubusercontent.com/Wels112/jarvis/main/install.ps1 | iex
#
# Что делает: находит настоящий Python, кладёт проект и окружение на диск с
# местом, ставит зависимости, скачивает модель распознавания, спрашивает ключи
# и проверяет, что всё живо. Ничего не ставит в систему мимо своей папки.
#
# Файл сохранён с BOM намеренно: PowerShell 5.1 читает UTF-8 без BOM как ANSI
# и портит русский текст.
#
# Без вопросов (для проверки и для установки на чужой машине заранее):
#   .\install.ps1 -Unattended -Root D:\jarvis -GeminiKey ключ

param(
    [switch]$Unattended,      # ничего не спрашивать, брать значения из параметров
    [string]$Root,            # куда ставить
    [string]$GeminiKey,
    [string]$BotToken,
    [string]$OwnerName,
    [switch]$NoShortcut       # не класть ярлык на рабочий стол
)

$ErrorActionPreference = 'Stop'
# Без полос прогресса: при проверке 05.10.2026 Expand-Archive залил ими весь
# экран, и собственные сообщения установщика потерялись. Побочная польза —
# Invoke-WebRequest без полосы качает заметно быстрее.
$ProgressPreference = 'SilentlyContinue'
$Repo = 'https://github.com/Wels112/jarvis'          # подставляется при публикации
$Branch = 'main'

function Шаг($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Готово($text) { Write-Host "    $text" -ForegroundColor Green }
function Беда($text) { Write-Host "    $text" -ForegroundColor Yellow }

# Запись без BOM. PowerShell 5.1 по «-Encoding utf8» ставит в начало файла
# невидимую метку, и Python на ней спотыкается: при проверке установки
# 05.10.2026 из-за неё не прочитались настройки и голос стал механическим.
function Save-Utf8($path, $text) {
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

Write-Host @'
  Джарвис — голосовой помощник для Windows
  Управляет компьютером, помнит дела, отвечает голосом.
'@ -ForegroundColor White

# --- 1. Python -------------------------------------------------------------
# «python» на PATH часто оказывается заглушкой из Microsoft Store: она ничего
# не делает и возвращает пустоту. Поэтому ищем через py и проверяем версию.
Шаг 'Ищу Python'
$python = $null
foreach ($try in @('py -3.12', 'py -3.11', 'py -3.10', 'py -3')) {
    $exe, $arg = $try.Split(' ', 2)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $v = & $exe $arg -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($v -match '^3\.(1[0-3])$') { $python = $try; break }
}
if (-not $python) {
    Беда 'Нужен Python 3.10-3.13. Поставь с python.org (галочку "Add to PATH" можно не ставить),'
    Беда 'потом запусти установщик снова.'
    Start-Process 'https://www.python.org/downloads/windows/'
    return
}
Готово "нашёл: $python"

# --- 2. Куда ставить -------------------------------------------------------
Шаг 'Выбираю диск'
$disks = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 6GB } |
         Sort-Object Free -Descending
if (-not $disks) { Беда 'Нужно хотя бы 6 ГБ свободного места.'; return }
$best = $disks[0].Name
foreach ($d in $disks) { Write-Host ("    {0}: свободно {1:N0} ГБ" -f $d.Name, ($d.Free / 1GB)) }
if ($Root) { $root = $Root }
elseif ($Unattended) { $root = "${best}:\jarvis" }
else {
    $answer = Read-Host "    Куда поставить? [${best}:\jarvis]"
    $root = if ($answer) { $answer } else { "${best}:\jarvis" }
}
New-Item -ItemType Directory -Force $root | Out-Null
Готово "ставлю в $root"

# --- 3. Код ----------------------------------------------------------------
# Скачиваем zip, а не клонируем: git у клиента может быть не установлен
Шаг 'Скачиваю код'
$zip = Join-Path $env:TEMP 'jarvis.zip'
Invoke-WebRequest "$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
$tmp = Join-Path $env:TEMP 'jarvis-unpack'
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
Expand-Archive $zip $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
Copy-Item "$($inner.FullName)\*" $root -Recurse -Force
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
Готово 'код на месте'

# --- 4. Окружение ----------------------------------------------------------
Шаг 'Собираю окружение (несколько минут)'
$exe, $arg = $python.Split(' ', 2)
& $exe $arg -m venv "$root\.venv"
$py = "$root\.venv\Scripts\python.exe"
# --no-cache-dir: кэш pip разрастается на гигабайты, а диск C: обычно забит
& $py -m pip install --upgrade pip --quiet --no-cache-dir
& $py -m pip install -r "$root\requirements.txt" --no-cache-dir
if ($LASTEXITCODE -ne 0) { Беда 'Не все зависимости встали — смотри сообщения выше.'; return }
Готово 'зависимости готовы'

# --- 5. Ключи --------------------------------------------------------------
Шаг 'Ключи'
$envFile = "$root\config\.env"
if (-not (Test-Path $envFile)) { Copy-Item "$root\config\.env.example" $envFile }
if (-not (Test-Path "$root\config\settings.json")) {
    Copy-Item "$root\config\settings.example.json" "$root\config\settings.json"
}
Write-Host '    Ключ Gemini бесплатный: aistudio.google.com/apikey'
Write-Host '    Без него работают только простые команды (время, громкость, программы).'
$key = if ($Unattended) { $GeminiKey } else { Read-Host '    Вставь ключ Gemini (Enter — пропустить)' }
if ($key) {
    Save-Utf8 $envFile ((Get-Content $envFile -Raw) -replace 'GEMINI_API_KEY=.*', "GEMINI_API_KEY=$key")
    Готово 'ключ записан'
}
Write-Host '    Чтобы управлять с телефона, нужен бот: напиши @BotFather команду /newbot'
$bot = if ($Unattended) { $BotToken } else { Read-Host '    Вставь токен бота (Enter — пропустить)' }
if ($bot) {
    Save-Utf8 $envFile ((Get-Content $envFile -Raw) -replace 'TELEGRAM_BOT_TOKEN=.*', "TELEGRAM_BOT_TOKEN=$bot")
    Готово 'токен записан, номер своего чата Джарвис подскажет при первом сообщении'
}
$name = if ($Unattended) { $OwnerName } else { Read-Host '    Как к тебе обращаться? [хозяин]' }
if ($name) {
    $s = Get-Content "$root\config\settings.json" -Raw | ConvertFrom-Json
    $s.owner = $name
    Save-Utf8 "$root\config\settings.json" ($s | ConvertTo-Json -Depth 9)
}

# --- 6. Модель распознавания ----------------------------------------------
Шаг 'Скачиваю модель распознавания речи (около 600 МБ)'
# Предупреждение про символические ссылки выглядит как поломка, хотя ничего не
# ломает: на Windows без режима разработчика их просто нет, файлы копируются
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
& $py -c @"
import sys
sys.path.insert(0, r'$root')
from core import config
from faster_whisper import WhisperModel
for size in ('tiny', 'small'):
    WhisperModel(size, device='cpu', compute_type='int8', download_root=str(config.MODELS))
    print('  готово:', size)
"@
Готово 'модель на месте'

# --- 7. Проверка -----------------------------------------------------------
Шаг 'Проверяю'
& $py "$root\setup.py" --check
# Ярлык кладём, только если это настоящая установка: при проверке он затёр бы
# рабочий ярлык хозяина, переставив его на тестовую папку
if (-not $NoShortcut) {
    $lnk = "$([Environment]::GetFolderPath('Desktop'))\Джарвис.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = "$root\jarvis.bat"
    $sc.WorkingDirectory = $root
    $sc.Save()
    Готово "ярлык на рабочем столе: Джарвис"
}

Write-Host "`nГотово. Запусти ярлык и скажи «Джарвис, привет»." -ForegroundColor Green
Write-Host "Автозапуск при включении компьютера: $root\автозапуск.bat`n"
