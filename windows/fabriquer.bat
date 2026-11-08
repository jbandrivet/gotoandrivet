@echo off
rem Fabrique les .exe dans la machine Windows. T: = dossier partagé préparé par preparer_vm.sh.
set B=C:\GotoBuild
(
if not exist %B% mkdir %B%
xcopy /e /i /q /y T:\Py312 %B%\Py312
xcopy /e /i /q /y T:\src %B%\src
xcopy /e /i /q /y T:\fabrication %B%\fabrication
%B%\Py312\python.exe -m venv %B%\env
%B%\env\Scripts\python.exe -m pip install --disable-pip-version-check pyinstaller pyserial pillow numpy requests ephem
set SRC=%B%\src
cd /d %B%\fabrication
%B%\env\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath %B%\dist --workpath %B%\build gotoandrivet.spec
xcopy /y %B%\dist\*.exe T:\sortie\
) > T:\journal.txt 2>&1
echo fini > T:\fini.txt
