using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

// Preserve byte streams and Windows argv quoting for the desktop app-server protocol.
internal static class Backend {
    static string Quote(string value) {
        var result = new StringBuilder("\"");
        int slash = 0;
        foreach (char c in value) {
            if (c == '\\') { slash++; continue; }
            result.Append('\\', c == '"' ? slash * 2 + 1 : slash);
            result.Append(c); slash = 0;
        }
        result.Append('\\', slash * 2); return result.Append('"').ToString();
    }
    static Thread Pump(Stream from, Stream to, bool close) {
        var worker = new Thread(delegate() {
            try { var bytes = new byte[32768]; int size;
                while ((size = from.Read(bytes,0,bytes.Length)) > 0) { to.Write(bytes,0,size); to.Flush(); }
            } catch (IOException) {} catch (ObjectDisposedException) {}
            finally { if(close) try {to.Close();} catch(IOException) {} }
        });
        worker.IsBackground=true; worker.Start(); return worker;
    }
    static int Main(string[] args) {
        string root=AppDomain.CurrentDomain.BaseDirectory;
        var command=new StringBuilder("-I -B "+Quote(Path.Combine(root,"bridge.py")));
        foreach(string arg in args) command.Append(' ').Append(Quote(arg));
        var start=new ProcessStartInfo(Path.Combine(root,@"runtime\python.exe"),command.ToString());
        start.UseShellExecute=false; start.CreateNoWindow=true;
        start.RedirectStandardInput=start.RedirectStandardOutput=start.RedirectStandardError=true;
        try { using(var child=Process.Start(start)) {
            Pump(Console.OpenStandardInput(), child.StandardInput.BaseStream,true);
            var output=Pump(child.StandardOutput.BaseStream,Console.OpenStandardOutput(),false);
            var errors=Pump(child.StandardError.BaseStream,Console.OpenStandardError(),false);
            child.WaitForExit(); output.Join(); errors.Join(); return child.ExitCode;
        }} catch(Exception ex) { Console.Error.WriteLine("Provider Card launcher: "+ex.GetType().Name); return 1; }
    }
}
