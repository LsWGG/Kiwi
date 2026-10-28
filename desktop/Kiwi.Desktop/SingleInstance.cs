using System.IO.Pipes;
using System.Text;

namespace Kiwi.Desktop;

/// <summary>
/// 单实例：命名 Mutex 与安装器 <c>AppMutex</c> 一致；第二个实例通过命名管道
/// 唤醒已有窗口后退出。
/// </summary>
internal sealed class SingleInstance : IDisposable
{
    public const string MutexName = "Kiwi.Desktop.SingleInstance";

    private readonly string _pipeName;
    private readonly CancellationTokenSource _cts = new();
    private Mutex? _mutex;
    private bool _first;

    public SingleInstance()
    {
        var user = Environment.UserName.Replace('\\', '_').Replace('/', '_');
        _pipeName = $"Kiwi.Desktop.Activate.{user}";
    }

    public event Action? ActivationRequested;

    /// <summary>返回 true 表示本进程是首个实例；false 表示已通知并应退出。</summary>
    public bool TryAcquire()
    {
        _mutex = new Mutex(initiallyOwned: true, MutexName, out var createdNew);
        _first = createdNew;
        if (createdNew)
        {
            StartListener();
        }
        else
        {
            SignalExisting();
        }
        return _first;
    }

    private void StartListener()
    {
        var thread = new Thread(ListenLoop)
        {
            IsBackground = true,
            Name = "Kiwi.Desktop.Activation",
        };
        thread.Start();
    }

    private void ListenLoop()
    {
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                using var server = new NamedPipeServerStream(
                    _pipeName,
                    PipeDirection.In,
                    maxNumberOfServerInstances: 1,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous);
                server.WaitForConnection();
                using var reader = new StreamReader(server, Encoding.UTF8);
                var message = reader.ReadLine();
                if (message == "activate")
                {
                    ActivationRequested?.Invoke();
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (ObjectDisposedException)
            {
                return;
            }
            catch (IOException)
            {
                Thread.Sleep(200);
            }
        }
    }

    private void SignalExisting()
    {
        try
        {
            using var client = new NamedPipeClientStream(".", _pipeName, PipeDirection.Out);
            client.Connect(2500);
            using var writer = new StreamWriter(client, new UTF8Encoding(false)) { AutoFlush = true };
            writer.WriteLine("activate");
        }
        catch (Exception)
        {
            // 管道不可用时只提示已有实例，不阻塞退出。
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        if (_first)
        {
            try
            {
                _mutex?.ReleaseMutex();
            }
            catch (ApplicationException)
            {
            }
        }
        _mutex?.Dispose();
        _cts.Dispose();
    }
}
