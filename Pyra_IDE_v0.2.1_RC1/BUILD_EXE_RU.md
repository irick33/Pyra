# Сборка Pyra 0.2.1 RC1 — Windows 10/11

Исходный архив не содержит готового Windows EXE. Сборщик нужно запускать на Windows.
Релиз остаётся RC до проверки обеих упаковок на этой платформе.

## Быстрый способ

В CMD из полностью распакованной папки проекта:

```bat
build_exe.bat onefile
build_exe.bat onedir
```

Без аргумента собирается onefile. `build_exe.bat both` создаёт обе упаковки.
Результаты: `dist\onefile\Pyra.exe` и `dist\onedir\Pyra\Pyra.exe`.
Для onedir передавайте пользователю **всю папку Pyra**, включая `_internal`.

Если Python установлен, например, на D: и не зарегистрирован в Launcher/PATH:

```bat
set "PYRA_BOOTSTRAP_PYTHON=D:\Папка Python\python.exe"
build_exe.bat both
```

Укажите реальный путь без дополнительных кавычек внутри значения. Python для
сборки — обычный CPython 3.10–3.15 с GIL. `start.bat --prepare-only` создаёт
окружение IDE; зависимости переустанавливаются только при изменении их файла.
PyInstaller зафиксирован в `requirements-build.txt`. Фактические версии
записываются в `dist\<mode>\build-info.json`.

## Ручная сборка

Если окружение уже подготовлено:

```powershell
.\.ide-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.ide-venv\Scripts\python.exe tools\build.py --mode both
```

Для диагностической сборки с консолью добавьте `--console`.
Сборщик сам определяет расположение Ruff, Jedi, parso и debugpy в выбранном
окружении. Жёсткой зависимости от `.ide-venv\Lib\site-packages` больше нет.

## Что находится в сборке

- Qt, QScintilla, pyte, Windows ConPTY/pywinpty.
- Нативный Ruff.
- Исходники Jedi/parso/debugpy и небольшого рабочего процесса Pyra.
- README, лицензия, список сторонних компонентов и демо-проект.

Упакованная IDE использует выбранный **внешний Python**, а не `Pyra.exe`, для
выполнения кода. Jedi и debugpy запускаются тем же реальным Python через
изолированный загрузчик `-I`. Их исходники берутся из сборки: устанавливать
их в проект не нужно. debugpy использует Python fallback вместо расширений,
скомпилированных для другой minor-версии Python. Это может влиять на скорость
отладки, но не на обычный Run. Файлы onefile доступны до закрытия IDE;
дочерние службы завершаются вместе с окном.

## Автоматическая проверка собранного EXE

В PowerShell (замените пути):

```powershell
$arguments = '--self-test --python "D:\Python315\python.exe" --report "D:\Pyra\selftest-onefile.json"'
$p = Start-Process -FilePath '.\dist\onefile\Pyra.exe' -ArgumentList $arguments -Wait -PassThru
$p.ExitCode
Get-Content 'D:\Pyra\selftest-onefile.json' -Encoding UTF8
```

Повторите для `.\dist\onedir\Pyra\Pyra.exe`, сменив имя отчёта.
Папка отчёта должна существовать. Успех: код 0 и `"passed": true`.
Проверка создаёт только собственный временный проект и окружение без pip,
не использует настройки вашей обычной сессии и не устанавливает пакеты в проект.
Проверяются открытие окна/файла, venv, ввод кириллицы, Run, Jedi, Ruff, breakpoint
и интерактивный ввод при отладке. Отчёт содержит этап и traceback при ошибке.

## Оставшаяся приёмка Windows

1. Выполнить автоматическую проверку для обеих упаковок.
2. Открыть IDE обычным двойным щелчком, выбрать проект на D: с кириллицей и пробелами.
3. Нажать «Найти Python», проверить Launcher, реестр, список и ручной выбор другого диска.
4. Проверить PowerShell: `python --version`, `input()`, Ctrl+C, закрытие терминала.
5. Создать `.venv`, переключить два Python, повторить запуск и отладку; перезапустить IDE.
6. Проверить «Справка → Журнал ошибок», в том числе при удалённом Python или ошибке Ruff.
7. Повторить запуск с непрогретым кешем после перезагрузки; зафиксировать Windows/CPU/RAM.

Инструменты замеров: `tools/benchmark.py`, `tools/benchmark_launch.py` и
`tools/benchmark_packaging.py`. Пример последнего из окружения разработки:

```powershell
python tools\benchmark_packaging.py run.py dist\onefile\Pyra.exe dist\onedir\Pyra\Pyra.exe --samples 7 --output packaging.json
```

Поиск не обходит все файлы всех дисков: это сохраняет отзывчивость. Нестандартный
путь выбирается вручную и затем запоминается. Глубокий поиск, автоскачивание Python,
обновление приложения и плагины в этой версии не добавлялись.
