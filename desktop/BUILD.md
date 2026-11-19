# Сборка окна Windows

Окно использует WinForms и Microsoft WebView2. Оно запускает локальный сервер штатным сценарием PowerShell. Аналитика, данные и форматы отчёта общие с браузерной сборкой.

Для сборки подготовьте Windows x64 с .NET Framework 4.6.2 или более новым и SDK Microsoft.Web.WebView2 версии 1.0.3856.49 из NuGet. Сохраните лицензии SDK при копировании библиотек.

Из пакета нужны Microsoft.Web.WebView2.Core.dll и Microsoft.Web.WebView2.WinForms.dll из lib/net462, а также WebView2Loader.dll из build/native/x64. Разместите три файла рядом с будущим EXE в корне проекта. Скомпилируйте desktop/KonturWindow.cs штатным компилятором csc с параметрами /target:winexe, /platform:x64 и /win32icon:desktop/kontur.ico. Подключите System, System.Core, System.Drawing, System.Windows.Forms и обе сборки WebView2.

Для запуска EXE требуется установленный Microsoft WebView2 Runtime. Вы можете использовать start_windows.cmd для запасного запуска в системном браузере.
