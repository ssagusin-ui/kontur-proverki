# Сборка Windows-приложения

Окно использует WinForms и Microsoft WebView2. Оно запускает локальный сервер штатным сценарием PowerShell. Аналитика, данные и форматы отчёта общие с браузерной сборкой.

Для сборки требуются Windows x64, .NET Framework 4.6.2 или более новая версия и SDK Microsoft.Web.WebView2 версии 1.0.3856.49 из NuGet. Лицензии SDK должны входить в комплект распространяемых библиотек.

Из пакета нужны Microsoft.Web.WebView2.Core.dll и Microsoft.Web.WebView2.WinForms.dll из lib/net462, а также WebView2Loader.dll из build/native/x64. Разместите три файла рядом с будущим EXE в корне проекта. Скомпилируйте desktop/KonturWindow.cs штатным компилятором csc с параметрами /target:winexe, /platform:x64 и /win32icon:desktop/kontur.ico. Подключите System, System.Core, System.Drawing, System.Windows.Forms и обе сборки WebView2.

Для запуска EXE требуется установленный Microsoft WebView2 Runtime. Запуск в системном браузере доступен через start_windows.cmd.
