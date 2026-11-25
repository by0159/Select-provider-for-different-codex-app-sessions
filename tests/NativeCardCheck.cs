using System;
using System.Reflection;
using System.Windows.Forms;

// Exercise the built native UI without showing a window or reading user credentials.
class NativeCardCheck {
    static void Assert(bool ok,string name){if(!ok)throw new Exception(name);}
    [STAThread] static void Main(string[] args){
        var assembly=Assembly.LoadFrom(args[0]);
        var type=assembly.GetType("Card");
        using(var card=(Form)Activator.CreateInstance(type,true)){
            var flags=BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic;
            ((Timer)type.GetField("timer",flags).GetValue(card)).Stop();
            var key=(TextBox)type.GetField("key",flags).GetValue(card);
            Assert(!key.UseSystemPasswordChar && key.PasswordChar=='\0',"Key must display plaintext");
            Assert(key.MaxLength==2200,"Key input length changed");
            Assert(assembly.GetType("Record").GetProperty("key")!=null,"Credential readback is absent");
            var record=assembly.GetType("SpeedRecord");var choice=Activator.CreateInstance(record);
            record.GetProperty("mode").SetValue(choice,"priority",null);record.GetProperty("effectiveTier").SetValue(choice,"priority",null);
            record.GetProperty("lastTier").SetValue(choice,"default",null);record.GetProperty("lastStatus").SetValue(choice,429,null);
            type.GetMethod("ShowSpeed",flags).Invoke(card,new[]{choice});
            var speed=(Button)type.GetField("speed",flags).GetValue(card);var menu=(ContextMenuStrip)type.GetField("speedMenu",flags).GetValue(card);
            Assert(speed.Text.Contains("Fast")&&speed.AccessibleName.Contains("速度选择"),"Speed picker missing");
            Assert(menu.Items.Count==3&&((ToolStripMenuItem)menu.Items[1]).Checked,"Wrong speed menu selection");
            Assert(((Label)type.GetField("speedStatus",flags).GetValue(card)).Text.Contains("HTTP 429"),"Previous HTTP error not shown");
            key.Text="visible-fixture-key";
            for(int i=0;i<3;i++)type.GetMethod("Toggle",flags).Invoke(card,new object[]{null,EventArgs.Empty});
            Assert(key.Text=="visible-fixture-key","Folding cleared the saved key");
            type.GetMethod("NewContext",flags).Invoke(card,new object[]{"fixture-next-thread"});
            Assert(key.Text=="","Switching thread retained the previous key");
            Assert(!speed.Enabled&&!((ToolStripMenuItem)menu.Items[1]).Checked,"New thread retained an old speed selection");
        }
        Console.WriteLine("PASS native card: speed menu, saved selection, HTTP status, key display and chat isolation.");
    }
}
