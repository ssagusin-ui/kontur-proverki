# Сборка Windows-приложения

Исполняемый файл «Контур проверки.exe» открывает окно WinForms с компонентом Microsoft WebView2. При запуске программа вызывает `scripts/start_windows.ps1` и загружает локальный интерфейс Streamlit. Оба способа доступа к интерфейсу используют одни и те же правила проверки, базу SQLite и форматы отчётов.

Для сборки требуются Windows x64, .NET Framework 4.6.2 или более новая версия и SDK Microsoft.Web.WebView2 версии 1.0.3856.49 из NuGet. Лицензии SDK должны входить в комплект распространяемых библиотек.

Скопируйте из пакета SDK в корень проекта три файла:

- `lib/net462/Microsoft.Web.WebView2.Core.dll`
- `lib/net462/Microsoft.Web.WebView2.WinForms.dll`
- `build/native/x64/WebView2Loader.dll`

Из корня проекта выполните в PowerShell команду сборки. Она создаст «Контур проверки.exe» рядом с библиотеками.

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" `
  /target:winexe /platform:x64 /win32icon:desktop\kontur.ico `
  '/out:Контур проверки.exe' `
  /reference:System.dll,System.Core.dll,System.Drawing.dll,System.Windows.Forms.dll `
  /reference:Microsoft.Web.WebView2.Core.dll,Microsoft.Web.WebView2.WinForms.dll `
  .\desktop\KonturWindow.cs
```

Для запуска из исходников установите зависимости Python с помощью `install_windows.cmd`. В переносимом выпуске они уже включены в папку `runtime`. Для работы окна нужен установленный Microsoft WebView2 Runtime. Если он недоступен, запасной запуск описан в [руководстве](../README.md).
