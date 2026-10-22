// OpenKitsune Windows 启动器（双击 exe → 弹独立 PowerShell 窗口显示启动检查 + 实时日志）
// 行为：
//   1) exe 编译为 GUI 子系统（WindowsApplication），双击不弹黑色控制台窗口
//   2) 拉起 powershell.exe 打开一个独立的 PowerShell 窗口，运行 manage.ps1 start -ShowLog：
//      彩色启动检查（[OK]/[WARN]/[FAIL]）→ 实时日志跟随（窗口常驻，Ctrl+C 或关闭窗口不影响后台 serve）
//   3) exe 自身立即退出；PowerShell 窗口由 manage.ps1 持有
// 编译（在 PowerShell 5.1 中，UTF-8 读取源码避免中文乱码）：
//   $winCs = [IO.File]::ReadAllText("D:\ai\OpenKitsune-main\tools\launcher_win.cs", [Text.Encoding]::UTF8)
//   Add-Type -TypeDefinition $winCs -OutputAssembly "D:\ai\OpenKitsune-main\OpenKitsunewinLauncher.exe" -OutputType WindowsApplication
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

public static class OpenKitsuneWinLauncher
{
    // 硬编码常量：仓库迁移后必须同步修改并重新编译，否则启动器会去旧路径找 manage.ps1
    private static readonly string ProjectRoot = @"D:\ai\OpenKitsune-main";
    private static readonly string ManagePs1 = Path.Combine(ProjectRoot, "manage.ps1");

    [STAThread]
    public static void Main()
    {
        if (!File.Exists(ManagePs1))
        {
            MessageBox.Show(
                "未找到管理脚本：\n" + ManagePs1 +
                "\n\n请检查 ProjectRoot 常量是否指向当前仓库，然后重新编译。",
                "OpenKitsune 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        try
        {
            // GUI 子系统进程没有父控制台，启动 powershell.exe（控制台程序）时
            // Windows 会自动为它分配一个新的控制台窗口 → 即用户看到的 PowerShell 窗口。
            // -NoExit 保证脚本（含 -ShowLog 日志跟随）结束后窗口仍保持常驻。
            var psi = new ProcessStartInfo("powershell.exe")
            {
                Arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -File \"" + ManagePs1 + "\" start -ShowLog",
                WorkingDirectory = ProjectRoot,
                UseShellExecute = false,
                CreateNoWindow = false
            };
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("启动失败: " + ex.Message,
                "OpenKitsune 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
