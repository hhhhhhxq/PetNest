param(
    [int]$CommandPort = 18488,
    [int]$EventPort = 18489,
    [int]$HostProcessId = 0,
    [string]$SelfTestFrame = "",
    [int]$SelfTestMilliseconds = 1200
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

public sealed class PetNestNativeBridge : IDisposable
{
    private readonly UdpClient receiver;
    private readonly UdpClient sender;
    private readonly IPEndPoint eventEndpoint;
    private readonly PetNestAlphaWindow window;
    private readonly Thread receiveThread;
    private volatile bool running;

    public PetNestNativeBridge(PetNestAlphaWindow target, int commandPort, int eventPort)
    {
        window = target;
        receiver = new UdpClient(new IPEndPoint(IPAddress.Loopback, commandPort));
        sender = new UdpClient();
        eventEndpoint = new IPEndPoint(IPAddress.Loopback, eventPort);
        receiveThread = new Thread(ReceiveLoop);
        receiveThread.IsBackground = true;
        receiveThread.Name = "PetNest native presenter commands";
    }

    public void Start()
    {
        running = true;
        receiveThread.Start();
        Send("READY");
    }

    public void Send(string message)
    {
        try
        {
            byte[] payload = Encoding.UTF8.GetBytes(message);
            sender.Send(payload, payload.Length, eventEndpoint);
        }
        catch (ObjectDisposedException)
        {
        }
        catch (SocketException)
        {
        }
    }

    private void ReceiveLoop()
    {
        IPEndPoint source = new IPEndPoint(IPAddress.Loopback, 0);
        while (running)
        {
            try
            {
                byte[] payload = receiver.Receive(ref source);
                string command = Encoding.UTF8.GetString(payload);
                if (!window.IsDisposed && window.IsHandleCreated)
                {
                    window.BeginInvoke(new Action<string>(window.ApplyCommand), command);
                }
            }
            catch (ObjectDisposedException)
            {
                break;
            }
            catch (SocketException)
            {
                if (!running) break;
            }
            catch (InvalidOperationException)
            {
                if (!running) break;
            }
        }
    }

    public void Dispose()
    {
        running = false;
        receiver.Close();
        sender.Close();
    }
}

public sealed class PetNestAlphaWindow : Form
{
    private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);

    [StructLayout(LayoutKind.Sequential)]
    private struct NativePoint
    {
        public int X;
        public int Y;
        public NativePoint(int x, int y) { X = x; Y = y; }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeSize
    {
        public int X;
        public int Y;
        public NativeSize(int x, int y) { X = x; Y = y; }
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct BlendFunction
    {
        public byte Op;
        public byte Flags;
        public byte Alpha;
        public byte Format;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LastInputInfo
    {
        public uint Size;
        public uint Time;
    }

    [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr window);
    [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc, IntPtr value);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr value);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr parameter);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int maximumCount);
    [DllImport("user32.dll")] private static extern int GetWindowTextLength(IntPtr window);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern bool BringWindowToTop(IntPtr window);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")] private static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
    [DllImport("user32.dll")] private static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] private static extern bool GetLastInputInfo(ref LastInputInfo info);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr LoadImage(IntPtr instance, string name, uint type, int width, int height, uint flags);
    [DllImport("user32.dll")] private static extern bool SetSystemCursor(IntPtr cursor, uint identifier);
    [DllImport("user32.dll")] private static extern bool DestroyCursor(IntPtr cursor);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern bool SystemParametersInfo(uint action, uint parameter, IntPtr value, uint flags);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UpdateLayeredWindow(
        IntPtr window,
        IntPtr screenDc,
        ref NativePoint destination,
        ref NativeSize size,
        IntPtr sourceDc,
        ref NativePoint source,
        int colorKey,
        ref BlendFunction blend,
        int flags
    );

    private const int WsExLayered = 0x00080000;
    private const int WsExToolWindow = 0x00000080;
    private const int WsExTransparent = 0x00000020;
    private const int WsExNoActivate = 0x08000000;
    private const int UlwAlpha = 0x00000002;
    private const int WmNcHitTest = 0x0084;
    private const int HtTransparent = -1;
    private const int SwHide = 0;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpNoActivate = 0x0010;
    private static readonly IntPtr HwndTopmost = new IntPtr(-1);
    private static readonly IntPtr HwndNotTopmost = new IntPtr(-2);
    private const byte AcSrcOver = 0;
    private const byte AcSrcAlpha = 1;
    private const uint ImageCursor = 2;
    private const uint LoadFromFile = 0x0010;
    private const uint SpiSetCursors = 0x0057;
    private static readonly Dictionary<string, uint> CursorRoles = new Dictionary<string, uint>
    {
        { "arrow", 32512 }, { "text", 32513 }, { "busy", 32514 },
        { "resize_diag_1", 32642 }, { "resize_diag_2", 32643 },
        { "resize_horizontal", 32644 }, { "resize_vertical", 32645 }, { "move", 32646 }
    };

    private readonly Dictionary<string, Bitmap> sourceFrames = new Dictionary<string, Bitmap>();
    private readonly int hostProcessId;
    private readonly System.Windows.Forms.Timer hostWindowTimer;
    private readonly Stopwatch idleBroadcastStopwatch = Stopwatch.StartNew();
    private readonly PetNestCardWindow countdownWindow;
    private PetNestNativeBridge bridge;
    private Bitmap renderedFrame;
    private string renderedPath = "";
    private int renderedWidth;
    private int renderedHeight;
    private bool renderedFlipHorizontal;
    private bool presenterVisible = true;
    private bool closing;
    private bool desiredTopmost = true;
    private bool cursorThemeApplied;

    public static void EnablePerMonitorDpiAwareness()
    {
        try
        {
            if (!SetProcessDpiAwarenessContext(new IntPtr(-4))) SetProcessDPIAware();
        }
        catch (EntryPointNotFoundException)
        {
            SetProcessDPIAware();
        }
    }

    private sealed class PetNestCardWindow : Form
    {
        private Bitmap renderedCard;
        private string renderedText = "";
        private string renderedTheme = "";
        private int renderedWidth;
        private int renderedHeight;
        private bool parentVisible = true;
        private bool contentVisible;
        private bool desiredTopmost = true;

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams parameters = base.CreateParams;
                parameters.ExStyle |= WsExLayered | WsExToolWindow | WsExTransparent | WsExNoActivate;
                return parameters;
            }
        }

        public PetNestCardWindow()
        {
            Text = "PetNest Countdown Presenter";
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            TopMost = true;
            StartPosition = FormStartPosition.Manual;
            ClientSize = new Size(1, 1);
            Location = new Point(-10000, -10000);
        }

        public void PresentCard(string text, int left, int top, int width, int height, string theme, bool visible)
        {
            contentVisible = visible && !String.IsNullOrEmpty(text);
            if (!contentVisible)
            {
                Hide();
                return;
            }
            bool mustRender = renderedCard == null || renderedText != text || renderedTheme != theme ||
                renderedWidth != width || renderedHeight != height;
            if (mustRender)
            {
                Bitmap nextCard = RenderCard(text, width, height, theme);
                Bitmap previous = renderedCard;
                renderedCard = nextCard;
                renderedText = text;
                renderedTheme = theme;
                renderedWidth = width;
                renderedHeight = height;
                if (previous != null) previous.Dispose();
            }
            SetBounds(left, top, width, height);
            if (parentVisible)
            {
                if (!Visible) Show();
                PresentLayeredCard();
                EnforceTopmost();
            }
        }

        public void SetParentVisible(bool value)
        {
            parentVisible = value;
            if (!value || !contentVisible)
            {
                Hide();
            }
            else if (renderedCard != null)
            {
                Show();
                PresentLayeredCard();
                EnforceTopmost();
            }
        }

        public void SetAlwaysOnTop(bool value)
        {
            desiredTopmost = value;
            TopMost = value;
            EnforceTopmost();
        }

        private void EnforceTopmost()
        {
            if (!IsHandleCreated) return;
            SetWindowPos(
                Handle,
                desiredTopmost ? HwndTopmost : HwndNotTopmost,
                0, 0, 0, 0,
                SwpNoMove | SwpNoSize | SwpNoActivate
            );
        }

        private static Bitmap RenderCard(string text, int width, int height, string theme)
        {
            Bitmap card = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
            Color background;
            Color border;
            Color foreground;
            switch (theme)
            {
                case "night":
                    background = Color.FromArgb(225, 20, 26, 38);
                    border = Color.FromArgb(235, 115, 158, 235);
                    foreground = Color.FromArgb(255, 240, 245, 255);
                    break;
                case "yarn":
                    background = Color.FromArgb(230, 235, 189, 179);
                    border = Color.FromArgb(235, 140, 77, 82);
                    foreground = Color.FromArgb(255, 64, 31, 33);
                    break;
                default:
                    background = Color.FromArgb(230, 250, 232, 184);
                    border = Color.FromArgb(235, 163, 117, 66);
                    foreground = Color.FromArgb(255, 51, 38, 26);
                    break;
            }
            using (Graphics graphics = Graphics.FromImage(card))
            {
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.Clear(Color.Transparent);
                graphics.CompositingMode = CompositingMode.SourceOver;
                graphics.CompositingQuality = CompositingQuality.HighQuality;
                graphics.SmoothingMode = SmoothingMode.AntiAlias;
                graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                float radius = Math.Max(5.0f, Math.Min(12.0f, height * 0.28f));
                using (GraphicsPath path = RoundedRectangle(new RectangleF(0.75f, 0.75f, width - 1.5f, height - 1.5f), radius))
                using (SolidBrush backgroundBrush = new SolidBrush(background))
                using (Pen borderPen = new Pen(border, 1.25f))
                {
                    graphics.FillPath(backgroundBrush, path);
                    graphics.DrawPath(borderPen, path);
                }
                float fontSize = Math.Max(10.0f, Math.Min(18.0f, height * 0.38f));
                using (Font font = new Font("Microsoft YaHei UI", fontSize, FontStyle.Bold, GraphicsUnit.Pixel))
                using (SolidBrush textBrush = new SolidBrush(foreground))
                using (StringFormat format = new StringFormat())
                {
                    format.Alignment = StringAlignment.Center;
                    format.LineAlignment = StringAlignment.Center;
                    format.Trimming = StringTrimming.EllipsisCharacter;
                    graphics.DrawString(text, font, textBrush, new RectangleF(7, 1, width - 14, height - 2), format);
                }
            }
            return card;
        }

        private static GraphicsPath RoundedRectangle(RectangleF rectangle, float radius)
        {
            float diameter = radius * 2.0f;
            GraphicsPath path = new GraphicsPath();
            path.AddArc(rectangle.Left, rectangle.Top, diameter, diameter, 180, 90);
            path.AddArc(rectangle.Right - diameter, rectangle.Top, diameter, diameter, 270, 90);
            path.AddArc(rectangle.Right - diameter, rectangle.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(rectangle.Left, rectangle.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }

        private void PresentLayeredCard()
        {
            if (renderedCard == null) return;
            IntPtr screen = GetDC(IntPtr.Zero);
            IntPtr memory = CreateCompatibleDC(screen);
            IntPtr bitmap = renderedCard.GetHbitmap(Color.FromArgb(0));
            IntPtr previous = IntPtr.Zero;
            try
            {
                previous = SelectObject(memory, bitmap);
                NativePoint destination = new NativePoint(Left, Top);
                NativeSize size = new NativeSize(renderedCard.Width, renderedCard.Height);
                NativePoint source = new NativePoint(0, 0);
                BlendFunction blend = new BlendFunction
                {
                    Op = AcSrcOver,
                    Flags = 0,
                    Alpha = 255,
                    Format = AcSrcAlpha
                };
                if (!UpdateLayeredWindow(
                    Handle, screen, ref destination, ref size, memory, ref source, 0, ref blend, UlwAlpha
                ))
                {
                    throw new InvalidOperationException("Countdown UpdateLayeredWindow failed: " + Marshal.GetLastWin32Error());
                }
            }
            finally
            {
                if (previous != IntPtr.Zero) SelectObject(memory, previous);
                DeleteObject(bitmap);
                DeleteDC(memory);
                ReleaseDC(IntPtr.Zero, screen);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && renderedCard != null) renderedCard.Dispose();
            base.Dispose(disposing);
        }
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams parameters = base.CreateParams;
            parameters.ExStyle |= WsExLayered | WsExToolWindow;
            return parameters;
        }
    }

    public PetNestAlphaWindow(int hostProcess)
    {
        hostProcessId = hostProcess;
        countdownWindow = new PetNestCardWindow();
        Text = "PetNest Advanced Presenter";
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        TopMost = true;
        StartPosition = FormStartPosition.Manual;
        ClientSize = new Size(1, 1);
        Location = new Point(-10000, -10000);

        MouseEnter += delegate { SendEvent("ENTER"); };
        MouseLeave += delegate { SendEvent("LEAVE"); };
        MouseDown += delegate(object sender, MouseEventArgs eventArgs)
        {
            SendMouseEvent("DOWN", eventArgs.Button);
        };
        MouseUp += delegate(object sender, MouseEventArgs eventArgs)
        {
            SendMouseEvent("UP", eventArgs.Button);
        };
        MouseMove += delegate { SendMouseEvent("MOVE", MouseButtons.None); };
        MouseDoubleClick += delegate(object sender, MouseEventArgs eventArgs)
        {
            SendMouseEvent("DOUBLE", eventArgs.Button);
        };
        FormClosed += delegate
        {
            countdownWindow.Close();
            if (!closing) SendEvent("CLOSED");
        };
        hostWindowTimer = new System.Windows.Forms.Timer();
        hostWindowTimer.Interval = 100;
        hostWindowTimer.Tick += delegate
        {
            if (!HostProcessIsRunning())
            {
                closing = true;
                Close();
                return;
            }
            HideHostRenderWindow();
            if (idleBroadcastStopwatch.ElapsedMilliseconds >= 900)
            {
                idleBroadcastStopwatch.Restart();
                BroadcastSystemIdle();
            }
        };
        Shown += delegate
        {
            HideHostRenderWindow();
            hostWindowTimer.Start();
        };
    }

    public void SetBridge(PetNestNativeBridge value)
    {
        bridge = value;
    }

    public void ApplyCommand(string command)
    {
        string[] parts = command.Split('\t');
        if (parts.Length == 0) return;
        try
        {
            switch (parts[0])
            {
                case "FRAME":
                    if (parts.Length >= 7)
                    {
                        string path = Encoding.UTF8.GetString(Convert.FromBase64String(parts[1]));
                        PresentFrame(
                            path,
                            Int32.Parse(parts[2]),
                            Int32.Parse(parts[3]),
                            Math.Max(1, Int32.Parse(parts[4])),
                            Math.Max(1, Int32.Parse(parts[5])),
                            parts[6] == "1"
                        );
                    }
                    break;
                case "COUNTDOWN":
                    if (parts.Length >= 8)
                    {
                        string text = Encoding.UTF8.GetString(Convert.FromBase64String(parts[1]));
                        countdownWindow.PresentCard(
                            text,
                            Int32.Parse(parts[2]),
                            Int32.Parse(parts[3]),
                            Math.Max(1, Int32.Parse(parts[4])),
                            Math.Max(1, Int32.Parse(parts[5])),
                            parts[6],
                            parts[7] == "1"
                        );
                    }
                    break;
                case "VISIBLE":
                    SetPresenterVisible(parts.Length >= 2 && parts[1] == "1");
                    break;
                case "TOPMOST":
                    SetAlwaysOnTop(parts.Length >= 2 && parts[1] == "1");
                    break;
                case "CURSOR":
                    if (parts.Length >= 2 && parts[1] == "1" && parts.Length >= 3)
                    {
                        ApplyCursorTheme(Encoding.UTF8.GetString(Convert.FromBase64String(parts[2])));
                    }
                    else
                    {
                        RestoreSystemCursorTheme();
                        SendEvent("CURSOR_APPLIED\t0");
                    }
                    break;
                case "FOCUS_POPUP":
                    FocusHostPopup();
                    break;
                case "QUIT":
                    closing = true;
                    countdownWindow.Close();
                    Close();
                    break;
            }
        }
        catch (Exception exception)
        {
            SendEvent("ERROR\t" + Convert.ToBase64String(Encoding.UTF8.GetBytes(exception.Message)));
        }
    }

    private Bitmap LoadSourceFrame(string path)
    {
        Bitmap cached;
        if (sourceFrames.TryGetValue(path, out cached)) return cached;

        using (Bitmap loaded = new Bitmap(path))
        {
            cached = new Bitmap(loaded.Width, loaded.Height, PixelFormat.Format32bppPArgb);
            using (Graphics graphics = Graphics.FromImage(cached))
            {
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.DrawImageUnscaled(loaded, 0, 0);
            }
        }
        sourceFrames[path] = cached;
        return cached;
    }

    private void PresentFrame(string path, int left, int top, int width, int height, bool flipHorizontal)
    {
        bool mustRender = renderedFrame == null || renderedPath != path || renderedWidth != width ||
            renderedHeight != height || renderedFlipHorizontal != flipHorizontal;
        if (mustRender)
        {
            Bitmap source = LoadSourceFrame(path);
            Bitmap nextFrame = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
            using (Graphics graphics = Graphics.FromImage(nextFrame))
            {
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.CompositingQuality = CompositingQuality.HighQuality;
                graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                graphics.SmoothingMode = SmoothingMode.HighQuality;
                if (flipHorizontal)
                {
                    graphics.TranslateTransform(width, 0);
                    graphics.ScaleTransform(-1.0f, 1.0f);
                }
                graphics.DrawImage(source, new Rectangle(0, 0, width, height));
            }
            Bitmap previous = renderedFrame;
            renderedFrame = nextFrame;
            renderedPath = path;
            renderedWidth = width;
            renderedHeight = height;
            renderedFlipHorizontal = flipHorizontal;
            if (previous != null) previous.Dispose();
        }

        SetBounds(left, top, width, height);
        if (presenterVisible)
        {
            if (!Visible) Show();
            PresentLayeredBitmap();
            EnforceTopmost();
        }
    }

    private void SetPresenterVisible(bool value)
    {
        presenterVisible = value;
        countdownWindow.SetParentVisible(value);
        if (!value)
        {
            Hide();
        }
        else if (renderedFrame != null)
        {
            Show();
            PresentLayeredBitmap();
            EnforceTopmost();
        }
    }

    private void SetAlwaysOnTop(bool value)
    {
        desiredTopmost = value;
        TopMost = value;
        EnforceTopmost();
        countdownWindow.SetAlwaysOnTop(value);
    }

    private void EnforceTopmost()
    {
        if (!IsHandleCreated) return;
        SetWindowPos(
            Handle,
            desiredTopmost ? HwndTopmost : HwndNotTopmost,
            0, 0, 0, 0,
            SwpNoMove | SwpNoSize | SwpNoActivate
        );
    }

    private void PresentLayeredBitmap()
    {
        if (renderedFrame == null) return;
        IntPtr screen = GetDC(IntPtr.Zero);
        IntPtr memory = CreateCompatibleDC(screen);
        IntPtr bitmap = renderedFrame.GetHbitmap(Color.FromArgb(0));
        IntPtr previous = IntPtr.Zero;
        try
        {
            previous = SelectObject(memory, bitmap);
            NativePoint destination = new NativePoint(Left, Top);
            NativeSize size = new NativeSize(renderedFrame.Width, renderedFrame.Height);
            NativePoint source = new NativePoint(0, 0);
            BlendFunction blend = new BlendFunction
            {
                Op = AcSrcOver,
                Flags = 0,
                Alpha = 255,
                Format = AcSrcAlpha
            };
            if (!UpdateLayeredWindow(
                Handle, screen, ref destination, ref size, memory, ref source, 0, ref blend, UlwAlpha
            ))
            {
                throw new InvalidOperationException("UpdateLayeredWindow failed: " + Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            if (previous != IntPtr.Zero) SelectObject(memory, previous);
            DeleteObject(bitmap);
            DeleteDC(memory);
            ReleaseDC(IntPtr.Zero, screen);
        }
    }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != WmNcHitTest || renderedFrame == null) return;
        Point local = PointToClient(Cursor.Position);
        if (local.X < 0 || local.Y < 0 || local.X >= renderedFrame.Width || local.Y >= renderedFrame.Height)
        {
            message.Result = new IntPtr(HtTransparent);
            return;
        }
        if (renderedFrame.GetPixel(local.X, local.Y).A < 8)
        {
            message.Result = new IntPtr(HtTransparent);
        }
    }

    private void SendMouseEvent(string kind, MouseButtons button)
    {
        Point cursor = Cursor.Position;
        SendEvent(kind + "\t" + MouseButtonNumber(button) + "\t" + cursor.X + "\t" + cursor.Y);
    }

    private static int MouseButtonNumber(MouseButtons button)
    {
        if (button == MouseButtons.Left) return 1;
        if (button == MouseButtons.Right) return 2;
        if (button == MouseButtons.Middle) return 3;
        return 0;
    }

    private void SendEvent(string message)
    {
        if (bridge != null) bridge.Send(message);
    }

    private void HideHostRenderWindow()
    {
        if (hostProcessId <= 0) return;
        EnumWindows(delegate(IntPtr candidate, IntPtr parameter)
        {
            uint candidateProcessId;
            GetWindowThreadProcessId(candidate, out candidateProcessId);
            if (candidateProcessId != (uint)hostProcessId || !IsWindowVisible(candidate)) return true;
            int titleLength = GetWindowTextLength(candidate);
            if (titleLength <= 0) return true;
            StringBuilder titleBuffer = new StringBuilder(titleLength + 1);
            GetWindowText(candidate, titleBuffer, titleBuffer.Capacity);
            string title = titleBuffer.ToString();
            if (title == "PetNest Advanced" || title.StartsWith("PetNest Advanced (", StringComparison.Ordinal))
            {
                ShowWindow(candidate, SwHide);
            }
            return true;
        }, IntPtr.Zero);
    }

    private void FocusHostPopup()
    {
        if (hostProcessId <= 0) return;
        IntPtr popup = IntPtr.Zero;
        EnumWindows(delegate(IntPtr candidate, IntPtr parameter)
        {
            uint candidateProcessId;
            GetWindowThreadProcessId(candidate, out candidateProcessId);
            if (candidateProcessId != (uint)hostProcessId || !IsWindowVisible(candidate)) return true;
            popup = candidate;
            return false;
        }, IntPtr.Zero);
        if (popup == IntPtr.Zero) return;
        BringWindowToTop(popup);
        SetForegroundWindow(popup);
    }

    private bool HostProcessIsRunning()
    {
        if (hostProcessId <= 0) return true;
        try
        {
            using (Process hostProcess = Process.GetProcessById(hostProcessId))
            {
                return !hostProcess.HasExited;
            }
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    private void BroadcastSystemIdle()
    {
        LastInputInfo input = new LastInputInfo();
        input.Size = (uint)Marshal.SizeOf(typeof(LastInputInfo));
        if (!GetLastInputInfo(ref input)) return;
        uint current = unchecked((uint)Environment.TickCount);
        uint elapsed = unchecked(current - input.Time);
        SendEvent("IDLE\t" + elapsed.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    private void ApplyCursorTheme(string root)
    {
        RestoreSystemCursorTheme();
        string directory = Path.GetFullPath(root);
        if (!Directory.Exists(directory))
        {
            SendEvent("CURSOR_APPLIED\t0");
            return;
        }
        bool applied = false;
        foreach (KeyValuePair<string, uint> role in CursorRoles)
        {
            string path = Path.Combine(directory, role.Key + ".cur");
            if (!File.Exists(path)) continue;
            IntPtr cursor = LoadImage(IntPtr.Zero, path, ImageCursor, 0, 0, LoadFromFile);
            if (cursor == IntPtr.Zero) continue;
            if (SetSystemCursor(cursor, role.Value))
            {
                applied = true;
            }
            else
            {
                DestroyCursor(cursor);
            }
        }
        cursorThemeApplied = applied;
        SendEvent("CURSOR_APPLIED\t" + (applied ? "1" : "0"));
    }

    private void RestoreSystemCursorTheme()
    {
        SystemParametersInfo(SpiSetCursors, 0, IntPtr.Zero, 0);
        cursorThemeApplied = false;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            if (cursorThemeApplied) RestoreSystemCursorTheme();
            hostWindowTimer.Stop();
            hostWindowTimer.Dispose();
            if (renderedFrame != null) renderedFrame.Dispose();
            foreach (Bitmap bitmap in sourceFrames.Values) bitmap.Dispose();
            sourceFrames.Clear();
            if (!countdownWindow.IsDisposed) countdownWindow.Dispose();
        }
        base.Dispose(disposing);
    }
}
'@ -ReferencedAssemblies System.Windows.Forms,System.Drawing,System

[PetNestAlphaWindow]::EnablePerMonitorDpiAwareness()
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$window = [PetNestAlphaWindow]::new($HostProcessId)
$bridge = [PetNestNativeBridge]::new($window, $CommandPort, $EventPort)
$window.SetBridge($bridge)
$window.Add_Shown({ $bridge.Start() })
if (-not [string]::IsNullOrWhiteSpace($SelfTestFrame)) {
    $encodedFrame = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($SelfTestFrame))
    $encodedCountdown = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("下班 01:23:45"))
    $workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $left = $workingArea.Right - 240
    $top = $workingArea.Bottom - 260
    $window.Add_Shown({
        $window.ApplyCommand("FRAME`t$encodedFrame`t$left`t$top`t220`t240`t0")
        $window.ApplyCommand("COUNTDOWN`t$encodedCountdown`t$($left + 30)`t$($top - 46)`t160`t38`tnight`t1")
        $script:selfTestTimer = [System.Windows.Forms.Timer]::new()
        $script:selfTestTimer.Interval = [Math]::Max(250, $SelfTestMilliseconds)
        $script:selfTestTimer.Add_Tick({
            $script:selfTestTimer.Stop()
            $window.ApplyCommand("QUIT")
        })
        $script:selfTestTimer.Start()
    })
}
try {
    [System.Windows.Forms.Application]::Run($window)
}
finally {
    $bridge.Dispose()
}
