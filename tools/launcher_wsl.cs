using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

public static class OpenKitsuneWslLauncher
{
    private static readonly string ProjectRoot = @"E:\agents\OpenKitsune-main";
    private static readonly string StartPs1 = Path.Combine(ProjectRoot, "start_wsl.ps1");
    private static readonly string WslLog = "/mnt/e/agents/OpenKitsune-main/data/logs/serve_wsl.log";

    [STAThread]
    public static void Main()
    {
        try { Console.Title = "OpenKitsune WSL 启动器"; } catch { }

        bool createdNew;
        using (Mutex instance = new Mutex(true, "OpenKitsuneWslLauncherInstance", out createdNew))
        {
            if (!createdNew)
            {
                Console.WriteLine("OpenKitsune WSL 启动器已在运行（现有窗口仍打开）。");
                Pause();
                return;
            }

            Console.WriteLine("OpenKitsune WSL 版启动中……（使用 WSL 内 Linux Python）");
            Console.WriteLine();
            if (!File.Exists(StartPs1))
            {
                Console.WriteLine("错误：未找到启动脚本 " + StartPs1);
                Pause();
                return;
            }
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("powershell.exe");
                psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + StartPs1 + "\"";
                psi.WorkingDirectory = ProjectRoot;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = false;
                Process p = Process.Start(psi);
                p.WaitForExit();
                int code = p.ExitCode;
                Console.WriteLine();
                if (code == 0)
                {
                    Console.ForegroundColor = ConsoleColor.Green;
                    Console.WriteLine("启动成功：浏览器已打开（http://127.0.0.1:18900/web/），WSL 服务已就绪。");
                    Console.ResetColor();
                    Console.WriteLine("服务日志: wsl -d Ubuntu -- tail -f " + WslLog);
                    Console.WriteLine();
                    Console.WriteLine("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
                    Console.WriteLine("以下为 WSL 服务实时日志（窗口常驻；关闭此窗口不影响服务运行）");
                    Console.WriteLine("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
                    try { Console.Title = "OpenKitsune WSL · 运行中"; } catch { }

                    ProcessStartInfo tail = new ProcessStartInfo("wsl.exe");
                    tail.Arguments = "-d Ubuntu -- tail -f " + WslLog;
                    tail.UseShellExecute = false;
                    tail.CreateNoWindow = false;
                    Process t = Process.Start(tail);
                    t.WaitForExit();
                    Console.WriteLine();
                    Console.WriteLine("实时日志已结束（退出码 " + t.ExitCode + "）。关闭窗口即可。");
                    Pause();
                }
                else
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("启动失败（退出码 " + code + "）。");
                    Console.ResetColor();
                    Console.WriteLine("排查日志：");
                    Console.WriteLine("  WSL 服务: wsl -d Ubuntu -- tail -n 50 " + WslLog);
                    Console.WriteLine("  手工启动试跑: powershell -ExecutionPolicy Bypass -File \"" + StartPs1 + "\"");
                    Pause();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine();
                Console.WriteLine("启动器异常: " + ex.Message);
                Pause();
            }
        }
    }

    private static void Pause()
    {
        try { Console.WriteLine(); Console.WriteLine("按任意键退出……"); Console.ReadKey(true); }
        catch { }
    }
}
