using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Контур проверки")]
[assembly: AssemblyProduct("Контур проверки")]
[assembly: AssemblyDescription("Рабочее место проверяющего")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string root = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
        string key;
        using (var hash = SHA256.Create())
            key = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(root.ToUpperInvariant()))).Replace("-", "");
        bool first;
        using (var instance = new Mutex(true, @"Local\KonturWindow-" + key, out first))
        using (var activate = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\KonturActivate-" + key))
        {
            if (!first)
            {
                activate.Set();
                return;
            }
            using (var form = new KonturForm(root, activate))
                Application.Run(form);
        }
    }
}

internal sealed class KonturForm : Form
{
    private readonly string root;
    private readonly EventWaitHandle activation;
    private readonly Panel splash;
    private readonly Label status;
    private readonly Button fallback;
    private readonly WebView2 view;
    private RegisteredWaitHandle activationWait;
    private Task<string> launching;
    private Uri localAddress;
    private string ownership;
    private bool closing;
    private bool closeComplete;

    public KonturForm(string root, EventWaitHandle activation)
    {
        this.root = root;
        this.activation = activation;
        Text = "Контур проверки";
        Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(760, 500);
        var area = Screen.PrimaryScreen.WorkingArea;
        Size = new Size(Math.Min(1350, area.Width - 40), Math.Min(900, area.Height - 36));
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(246, 249, 250);

        view = new WebView2 { Dock = DockStyle.Fill, Visible = false };
        Controls.Add(view);
        splash = new Panel { Dock = DockStyle.Fill };
        splash.Controls.Add(new Label {
            Text = "Контур проверки", AutoSize = true, Font = new Font("Segoe UI", 23, FontStyle.Bold),
            ForeColor = Color.FromArgb(16, 43, 62), Location = new Point(38, 36)
        });
        status = new Label {
            Text = "Подготавливаем рабочее место…", AutoSize = true, MaximumSize = new Size(620, 0),
            Font = new Font("Segoe UI", 12), ForeColor = Color.FromArgb(50, 76, 87),
            Location = new Point(41, 108)
        };
        fallback = new Button {
            Text = "Открыть в браузере", AutoSize = true, Visible = false,
            Location = new Point(42, 186), Padding = new Padding(10, 5, 10, 5)
        };
        fallback.Click += OpenFallback;
        splash.Controls.Add(status);
        splash.Controls.Add(fallback);
        Controls.Add(splash);
        Shown += Start;
    }

    private async void Start(object sender, EventArgs args)
    {
        activationWait = ThreadPool.RegisterWaitForSingleObject(activation, ActivateWindow, null, Timeout.Infinite, false);
        launching = RunLauncher("");
        try
        {
            ReadLaunchResult(await launching);
            if (closing) return;
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(root, "storage", "desktop-profile"));
            await view.EnsureCoreWebView2Async(environment);
            if (closing) return;

            var browser = view.CoreWebView2;
            browser.Settings.AreDevToolsEnabled = false;
            browser.Settings.AreDefaultContextMenusEnabled = false;
            browser.Settings.IsStatusBarEnabled = false;
            browser.NavigationStarting += (s, e) => e.Cancel = !IsLocal(e.Uri);
            browser.NewWindowRequested += (s, e) => e.Handled = true;
            browser.DownloadStarting += SaveDownload;
            browser.NavigationCompleted += (s, e) =>
            {
                if (closing) return;
                if (e.IsSuccess)
                {
                    splash.Visible = false;
                    view.Visible = true;
                    view.Focus();
                }
                else
                {
                    ShowStatus("Не удалось загрузить рабочее место.", true);
                }
            };
            browser.Navigate(localAddress.AbsoluteUri);
        }
        catch (Exception error)
        {
            Trace.WriteLine(error);
            if (!closing)
                ShowStatus(localAddress == null
                    ? "Программа не запустилась. Подробности находятся в storage/server.log."
                    : "Рабочее окно не открылось. Проверьте наличие Microsoft WebView2 Runtime.", true);
        }
    }

    private void ActivateWindow(object state, bool expired)
    {
        if (!IsHandleCreated || IsDisposed) return;
        try
        {
            BeginInvoke((MethodInvoker)delegate
            {
                if (WindowState == FormWindowState.Minimized)
                    WindowState = FormWindowState.Normal;
                Activate();
            });
        }
        catch (InvalidOperationException) { }
    }

    private void ReadLaunchResult(string output)
    {
        var match = Regex.Match(output, @"(?m)^http://127\.0\.0\.1:(85(?:1[7-9]|2[0-9]|3[0-6]))\s*$");
        if (!match.Success)
            throw new InvalidOperationException("Launcher returned no local address.");
        localAddress = new Uri(match.Value.Trim());
        var token = Regex.Match(output, @"(?m)^KONTUR_OWNER=(\d+),(\d+)\s*$");
        if (token.Success)
            ownership = "-ExpectedProcessId " + token.Groups[1].Value + " -ExpectedStart " + token.Groups[2].Value;
    }

    private bool IsLocal(string value)
    {
        Uri candidate;
        return Uri.TryCreate(value, UriKind.Absolute, out candidate)
            && candidate.Scheme == localAddress.Scheme
            && candidate.Host == localAddress.Host && candidate.Port == localAddress.Port;
    }

    private void SaveDownload(object sender, CoreWebView2DownloadStartingEventArgs args)
    {
        args.Handled = true;
        var deferral = args.GetDeferral();
        BeginInvoke((MethodInvoker)delegate
        {
            try
            {
                using (var dialog = new SaveFileDialog {
                    Title = "Сохранить файл", FileName = Path.GetFileName(args.ResultFilePath), OverwritePrompt = true
                })
                {
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                        args.ResultFilePath = dialog.FileName;
                    else
                        args.Cancel = true;
                }
            }
            finally { deferral.Complete(); }
        });
    }

    private async Task<string> RunLauncher(string arguments)
    {
        var script = Path.Combine(root, "scripts", "start_windows.ps1");
        var start = string.IsNullOrEmpty(arguments);
        var result = start ? Path.Combine(root, "storage", "desktop-" + Guid.NewGuid().ToString("N") + ".txt") : null;
        if (start)
            arguments = "-DesktopResult \"" + result + "\"";
        var info = new ProcessStartInfo {
            FileName = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -NoWindow " + arguments,
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = root,
        };
        try
        {
            using (var process = Process.Start(info))
            {
                await Task.Run(() => process.WaitForExit());
                if (process.ExitCode != 0)
                    throw new InvalidOperationException("Windows launcher exited with code " + process.ExitCode);
                return start ? File.ReadAllText(result) : "";
            }
        }
        finally
        {
            if (result != null && File.Exists(result))
                File.Delete(result);
        }
    }

    private void ShowStatus(string text, bool allowFallback)
    {
        view.Visible = false;
        splash.Visible = true;
        status.Text = text;
        fallback.Visible = allowFallback && localAddress != null;
    }

    private void OpenFallback(object sender, EventArgs args)
    {
        try
        {
            Process.Start(new ProcessStartInfo(localAddress.AbsoluteUri) { UseShellExecute = true });
            ownership = null;
        }
        catch (Exception error)
        {
            Trace.WriteLine(error);
            status.Text = "Откройте адрес из storage/address.txt в браузере.";
        }
    }

    protected override async void OnFormClosing(FormClosingEventArgs args)
    {
        base.OnFormClosing(args);
        if (closeComplete || args.CloseReason == CloseReason.WindowsShutDown)
            return;
        args.Cancel = true;
        if (closing) return;
        closing = true;
        if (activationWait != null)
            activationWait.Unregister(null);
        ShowStatus("Завершаем работу…", false);
        try
        {
            if (launching != null && localAddress == null)
                ReadLaunchResult(await launching);
            if (ownership != null)
                await RunLauncher("-Stop " + ownership);
        }
        catch (Exception error) { Trace.WriteLine(error); }
        closeComplete = true;
        Close();
    }
}
