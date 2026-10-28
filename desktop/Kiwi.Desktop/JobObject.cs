using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Kiwi.Desktop;

/// <summary>
/// Windows Job Object：宿主加入后，其子进程（runtime / PostgreSQL / Qdrant）默认
/// 继承同一个 Job；宿主崩溃或退出时由 <c>KILL_ON_JOB_CLOSE</c> 清理整棵进程树。
/// </summary>
internal sealed class JobObject : IDisposable
{
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const uint JobObjectLimitActiveProcess = 0x00000008;
    private const uint JobObjectLimitProcessMemory = 0x00000100;

    private IntPtr _handle;

    public JobObject()
    {
        _handle = CreateJobObject(IntPtr.Zero, null);
        if (_handle == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "创建 Job Object 失败");
        }

        var info = new JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new JobObjectBasicLimitInformation
            {
                LimitFlags = JobObjectLimitKillOnJobClose
                    | JobObjectLimitActiveProcess
                    | JobObjectLimitProcessMemory,
                ActiveProcessLimit = 64,
            },
            ProcessMemoryLimit = new UIntPtr(2UL * 1024 * 1024 * 1024),
            JobMemoryLimit = new UIntPtr(8UL * 1024 * 1024 * 1024),
        };

        var size = Marshal.SizeOf<JobObjectExtendedLimitInformation>();
        var pointer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, pointer, false);
            if (!SetInformationJobObject(
                    _handle, JobObjectExtendedLimitInformation, pointer, (uint)size))
            {
                var error = Marshal.GetLastWin32Error();
                CloseHandle(_handle);
                _handle = IntPtr.Zero;
                throw new Win32Exception(error, "配置 Job Object 失败");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(pointer);
        }
    }

    /// <summary>把当前进程加入 Job；之后启动的子进程会自动继承。</summary>
    public void AssignSelf()
    {
        using var current = Process.GetCurrentProcess();
        Assign(current);
    }

    /// <summary>把已启动的子进程加入同一 Job（继承已覆盖时是幂等操作）。</summary>
    public void Assign(Process process)
    {
        if (_handle == IntPtr.Zero)
        {
            return;
        }
        if (!AssignProcessToJobObject(_handle, process.Handle))
        {
            // 子进程可能已通过父进程继承进入 Job；错误 5 时继续运行。
            var error = Marshal.GetLastWin32Error();
            if (error != 5)
            {
                throw new Win32Exception(error, "将进程加入 Job Object 失败");
            }
        }
    }

    public void Terminate(uint exitCode = 1)
    {
        if (_handle != IntPtr.Zero)
        {
            TerminateJobObject(_handle, exitCode);
        }
    }

    public void Dispose()
    {
        if (_handle == IntPtr.Zero)
        {
            return;
        }
        CloseHandle(_handle);
        _handle = IntPtr.Zero;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr jobAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, IntPtr info, uint infoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr job, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
}
