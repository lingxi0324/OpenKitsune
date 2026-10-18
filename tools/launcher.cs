using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

public static class OpenKitsuneLauncher
{
    private static readonly string ProjectRoot = @"C:\Users\Administrator\.OpenKitsune\OpenKitsune";
    private static readonly string StartPs1 = Path.Combine(ProjectRoot, "start.ps1");
    private static readonly string LogRoot = @"C:\Users\Administrator\.OpenKitsune\logs";

    [STAThread]
    public static void Main()
    {
        try { Console.Title = "OpenKitsune 启动器"; } catch { }

        // 单实例锁：窗口开着时拒绝重复启动（防止二次双击重复拉起）
        bool createdNew;
        using (Mutex instance = new Mutex(true, "OpenKitsuneLauncherInstance", out createdNew))
        {
            if (!createdNew)
            {
                Console.WriteLine("OpenKitsune 已在运行（现有窗口仍打开，已阻止重复启动）。");
                Console.WriteLine("如需重新启动，请先关闭现有窗口。");
                Pause();
                return;
            }

            Console.WriteLine("OpenKitsune 启动中……（以下为实时日志，请稍候）");
            Console.WriteLine();
            if (!File.Exists(StartPs1))
            {
                Console.WriteLine();
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
                    Console.WriteLine("启动成功：浏览器已打开（http://127.0.0.1:18900/web/），服务已就绪。");
                    Console.ResetColor();
                    Console.WriteLine("本次启动日志: " + FindLatestLog(LogRoot));
                    Console.WriteLine();
                    Console.WriteLine("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
                    Console.WriteLine("以下为 WSL 服务实时日志（窗口常驻；关闭此窗口不影响服务运行）");
                    Console.WriteLine("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
                    try { Console.Title = "OpenKitsune · 运行中（服务日志）"; } catch { }

                    // 实时滚动 WSL 服务日志，直到用户关闭窗口 / 按键中断
                    ProcessStartInfo tail = new ProcessStartInfo("wsl.exe");
                    tail.Arguments = "-d Ubuntu -- tail -f /home/administrator/.openkitsune/OpenKitsune/data/logs/serve_wsl.log";
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
                    Console.WriteLine("  本次启动: " + FindLatestLog(LogRoot));
                    Console.WriteLine("  WSL 服务: wsl -d Ubuntu -- tail -n 50 /home/administrator/.openkitsune/OpenKitsune/data/logs/serve_wsl.log");
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

    private static string FindLatestLog(string dir)
    {
        try
        {
            if (!Directory.Exists(dir)) return "(未生成，检查 " + dir + ")";
            string[] files = Directory.GetFiles(dir, "launcher_*.log");
            if (files.Length == 0) return "(未生成 launcher_*.log)";
            Array.Sort(files);
            return files[files.Length - 1];
        }
        catch { return "(无法读取日志目录)"; }
    }

    private static void Pause()
    {
        try { Console.WriteLine(); Console.WriteLine("按任意键退出……"); Console.ReadKey(true); }
        catch { }
    }
}
