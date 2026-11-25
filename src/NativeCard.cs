using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Automation;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Linq;
using A=System.Windows.Automation.AutomationElement;

static class Win {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr dpi);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hwnd, uint relation);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out int pid);
    [DllImport("user32.dll",EntryPoint="SetWindowLongPtrW")] public static extern IntPtr SetOwner(IntPtr hwnd,int index, IntPtr owner);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hwnd,IntPtr after,int x,int y,int w,int h,uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd,int mode);
}
class Anchor {
    public IntPtr Owner; public Rectangle Card,Root; public string Label; public int Dpi;
    static System.Windows.Automation.Condition Eq(AutomationProperty p,object value){return new PropertyCondition(p,value);}
    static Rectangle Box(A el){var r=el.Current.BoundingRectangle;return r.IsEmpty?Rectangle.Empty:Rectangle.FromLTRB((int)r.Left,(int)r.Top,(int)r.Right,(int)r.Bottom);}
    public static Anchor Read(IntPtr owner){
        if(owner==IntPtr.Zero || !Win.IsWindowVisible(owner) || Win.IsIconic(owner))return null;
        var root=A.FromHandle(owner);
        var titlebar=root.FindFirst(TreeScope.Descendants,new AndCondition(Eq(A.ControlTypeProperty,ControlType.ToolBar),new OrCondition(Eq(A.NameProperty,"聊天工具栏"),Eq(A.NameProperty,"Chat toolbar"),Eq(A.NameProperty,"Conversation toolbar"))));
        if(titlebar==null)return null;
        var title=titlebar.FindAll(TreeScope.Descendants,Eq(A.ControlTypeProperty,ControlType.Button)).Cast<A>().FirstOrDefault(e=>e.Current.ClassName.Contains("px-conversation-title-inline")||e.Current.ClassName.Contains("text-conversation-title"));
        if(title==null||String.IsNullOrWhiteSpace(title.Current.Name))return null;
        var alternatives=new[]{"输出内容","来源","Outputs","Sources"}.Select(t=>Eq(A.NameProperty,t)).ToArray();
        var headers=root.FindAll(TreeScope.Descendants,new AndCondition(Eq(A.ControlTypeProperty,ControlType.Button),new OrCondition(alternatives)));
        foreach(A header in headers){var ancestor=header;for(int n=0;n<5&&ancestor!=null;n++,ancestor=TreeWalker.RawViewWalker.GetParent(ancestor)){
            var css=ancestor.Current.ClassName;
            if(css.Contains("rounded-2xl")&&css.Contains("bg-surface-elevated-secondary")){
                var card=Box(ancestor);var window=Box(root);
                if(card.Width<140||card.Height<25||card.Left<window.Left+window.Width/2)continue;
                return new Anchor{Owner=owner,Card=card,Root=window,Label=title.Current.Name,Dpi=(int)Win.GetDpiForWindow(owner)};
            }
        }}return null;
    }
}
class Choice {public string id{get;set;} public string project{get;set;} public override string ToString(){return project+" · "+id;} }
class Record {public string id{get;set;} public string url{get;set;} public string key{get;set;} public string error{get;set;} public Choice[] choices{get;set;} }
class SpeedRecord {public string mode{get;set;} public string effectiveTier{get;set;} public string lastTier{get;set;} public int? lastStatus{get;set;} public string error{get;set;} }
class Store {
    public static readonly string Root=AppDomain.CurrentDomain.BaseDirectory;
    public static Record Call(string op,string label,string id,string url,string key){
        return Exchange<Record>(new {op,label,id,url,key});
    }
    public static SpeedRecord Speed(string op,string label,string id,string mode=null){
        return Exchange<SpeedRecord>(new {op,label,id,mode});
    }
    static T Exchange<T>(object request){
        var serializer=new JavaScriptSerializer();var info=new ProcessStartInfo(Path.Combine(Root,@"runtime\python.exe"),"-I -B \""+Path.Combine(Root,"native_store.py")+"\"");
        info.CreateNoWindow=true;info.UseShellExecute=false;info.RedirectStandardInput=true;info.RedirectStandardOutput=true;
        using(var p=Process.Start(info)){
            var raw=Encoding.UTF8.GetBytes(serializer.Serialize(request));var reply=p.StandardOutput.ReadToEndAsync();
            p.StandardInput.BaseStream.Write(raw,0,raw.Length);p.StandardInput.BaseStream.Close();
            if(!p.WaitForExit(4500)){p.Kill();throw new IOException();}return serializer.Deserialize<T>(reply.GetAwaiter().GetResult());
        }
    }
}
class Card : Form {
    readonly Color paper=Color.FromArgb(44,44,44), ink=Color.FromArgb(239,239,238), muted=Color.FromArgb(185,185,183), border=Color.FromArgb(63,63,63);
    Button heading,fold,save,reset,speed; Label subtitle,feedback,urlLabel,keyLabel,speedStatus; TextBox url,key; ComboBox options;
    readonly ContextMenuStrip speedMenu=new ContextMenuStrip(); readonly ToolTip speedTip=new ToolTip();
    readonly ToolStripMenuItem inherit=new ToolStripMenuItem("跟随 config.toml"),fast=new ToolStripMenuItem("Fast（优先）"),standard=new ToolStripMenuItem("标准");
    bool savingSpeed,speedReady;DateTime lastSpeedRead=DateTime.MinValue;
    readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();
    bool sampling,expanded,editingChoice,working,ready,canPlace; int dpi=96, generation; DateTime lastMatch=DateTime.MinValue;
    DateTime? noHostSince; Anchor anchor;string label="",thread="",saved="";IntPtr owner;
    protected override bool ShowWithoutActivation{get{return true;}}
    protected override CreateParams CreateParams{get{var cp=base.CreateParams;cp.ExStyle|=0x80;return cp;}}
    Button Btn(string s,EventHandler click){var b=new Button{Text=s,FlatStyle=FlatStyle.Flat,TextAlign=ContentAlignment.MiddleCenter,BackColor=paper,ForeColor=ink,UseVisualStyleBackColor=false,Cursor=Cursors.Hand,TabStop=true};b.FlatAppearance.BorderSize=0;b.FlatAppearance.MouseOverBackColor=border;b.Click+=click;Controls.Add(b);return b;}
    Label Lbl(string s){var l=new Label{Text=s,ForeColor=muted,TextAlign=ContentAlignment.MiddleLeft,AutoEllipsis=true};Controls.Add(l);return l;}
    TextBox Edit(string name,int maxLength){var e=new TextBox{AccessibleName=name,UseSystemPasswordChar=false,BorderStyle=BorderStyle.FixedSingle,BackColor=Color.FromArgb(32,32,32),ForeColor=ink,MaxLength=maxLength,AutoSize=false};Controls.Add(e);return e;}
    public Card(){AutoScaleMode=AutoScaleMode.None;FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;StartPosition=FormStartPosition.Manual;Text="会话提供方";BackColor=paper;DoubleBuffered=true;
        heading=Btn("会话提供方",Toggle);heading.TextAlign=ContentAlignment.MiddleLeft;fold=Btn("＋",Toggle);fold.AccessibleName="展开会话提供方";
        speed=Btn("\u26a1",(s,e)=>{if(ready&&speedReady&&!savingSpeed)speedMenu.Show(speed,new Point(0,speed.Height));});
        speed.AccessibleName="速度选择";speed.Enabled=false;speedTip.SetToolTip(speed,"选择此会话的请求速度");
        speedStatus=Lbl("");speedMenu.BackColor=paper;speedMenu.ForeColor=ink;
        speedMenu.Items.AddRange(new ToolStripItem[]{inherit,fast,standard});
        inherit.Click+=async(s,e)=>await ChangeSpeed("inherit");fast.Click+=async(s,e)=>await ChangeSpeed("priority");standard.Click+=async(s,e)=>await ChangeSpeed("default");
        subtitle=Lbl("");urlLabel=Lbl("API 基础地址");url=Edit("API 基础地址",1200);keyLabel=Lbl("API Key");key=Edit("API Key",2200);feedback=Lbl("");
        save=Btn("保存",async(s,e)=>await Write(false));save.BackColor=Color.FromArgb(67,78,68);reset=Btn("恢复默认",async(s,e)=>await Write(true));
        options=new ComboBox{DropDownStyle=ComboBoxStyle.DropDownList,Visible=false,AccessibleName="同名会话"};Controls.Add(options);options.SelectedIndexChanged+=async(s,e)=>{if(!editingChoice&&options.SelectedItem!=null){var choice=(Choice)options.SelectedItem;ResetSelection();await LoadRecord(choice.id);}};
        timer.Interval=650;timer.Tick+=async(s,e)=>await Scan();timer.Start();
    }
    int U(int px){return (int)Math.Round(px*dpi/96.0);} void Place(Control c,int x,int y,int width,int height){c.SetBounds(U(x),U(y),U(width),U(height));}
    void Toggle(object s,EventArgs e){expanded=!expanded;Arrange();}
    void ResetSelection(){generation++;thread="";saved="";key.Clear();url.Clear();ready=false;working=false;feedback.Text="";subtitle.Text="读取中…";
        savingSpeed=speedReady=false;lastSpeedRead=DateTime.MinValue;speedMenu.Close();speed.Enabled=false;speed.Text="\u26a1";speed.AccessibleName="速度选择";speedStatus.Text="";inherit.Checked=fast.Checked=standard.Checked=false;}
    void NewContext(string title){ResetSelection();label=title;options.Visible=false;options.Items.Clear();}
    bool Supported(IntPtr h){if(h==IntPtr.Zero)return false;int pid;Win.GetWindowThreadProcessId(h,out pid);try{using(var p=Process.GetProcessById(pid)){return (p.ProcessName.Equals("ChatGPT",StringComparison.OrdinalIgnoreCase)||p.ProcessName.Equals("Codex",StringComparison.OrdinalIgnoreCase))&&p.MainModule.FileName.IndexOf(@"\WindowsApps\OpenAI.Codex_",StringComparison.OrdinalIgnoreCase)>=0;}}catch{return false;}}
    IntPtr FindHost(IntPtr foreground){
        if(Supported(foreground))return foreground;
        if(Supported(owner))return owner;
        foreach(var candidate in Process.GetProcessesByName("ChatGPT").Concat(Process.GetProcessesByName("Codex")))using(candidate){
            var win=candidate.MainWindowHandle;
            if(win!=IntPtr.Zero && Supported(win))return win;
        }
        return IntPtr.Zero;
    }
    void DisplayCard(){
        if(!canPlace)return;
        // Place an owned utility window immediately above its host without taking focus
        // from other applications. No global topmost or mouse/keyboard hooks are used.
        if(!Visible){
            var predecessor=Win.GetWindow(owner,3);
            Show();
            if(predecessor!=Handle)Win.SetWindowPos(Handle,predecessor,0,0,0,0,0x0013);
        }
    }
    async Task Scan(){if(sampling)return;sampling=true;try{
        var fg=FindHost(Win.GetForegroundWindow());
        if(fg==IntPtr.Zero){if(Visible)Hide(); if(!noHostSince.HasValue)noHostSince=DateTime.UtcNow; else if((DateTime.UtcNow-noHostSince.Value).TotalSeconds>20)Application.ExitThread(); return;} noHostSince=null;
        var a=await Task.Run(()=>global::Anchor.Read(fg));
        if(a==null){if(Visible)Hide();return;}
        bool change=(owner!=a.Owner||label!=a.Label);owner=a.Owner;anchor=a;dpi=a.Dpi>0?a.Dpi:96;
        Win.SetOwner(Handle,-8,owner);
        if(change){NewContext(a.Label);lastMatch=DateTime.UtcNow;await LoadRecord(null);}
        else if(!ready&&options.Items.Count==0&&!working&&(DateTime.UtcNow-lastMatch).TotalSeconds>6){lastMatch=DateTime.UtcNow;await LoadRecord(null);}
        if(ready&&!savingSpeed&&!speedMenu.Visible&&(expanded||!speedReady)&&(DateTime.UtcNow-lastSpeedRead).TotalSeconds>3)await ReadSpeed();
        Arrange();DisplayCard();
    }catch{if(Visible)Hide();}finally{sampling=false;}}
    async Task LoadRecord(string pick){int g=generation;string title=label;working=true;try{
        var r=await Task.Run(()=>Store.Call("read",title,pick,null,null));if(g!=generation)return;
        if(r.choices!=null){editingChoice=true;options.Items.Clear();options.Items.AddRange(r.choices);options.SelectedIndex=-1;editingChoice=false;subtitle.Text="请选择同名会话";feedback.Text="请核对会话 ID 后再保存。";ready=false;}
        else if(r.error!=null){subtitle.Text="等待会话";feedback.Text=r.error;ready=false;}
        else{thread=r.id;saved=r.url??"";url.Text=saved;key.Text=r.key??"";ready=true;Status();await ReadSpeed();}
    }catch{if(g==generation){ready=false;feedback.Text="无法读取会话设置。";}}finally{if(g==generation){working=false;Arrange();}}}
    void Status(){subtitle.Text=saved.Length==0?"跟随 config.toml":new Uri(saved).Host;}
    async Task Write(bool clear){if(!ready||working||anchor==null)return;working=true;save.Enabled=reset.Enabled=false;int g=generation;string t=thread,l=label,u=url.Text.Trim(),k=key.Text.Trim();try{
        var fresh=await Task.Run(()=>global::Anchor.Read(owner));if(fresh==null||fresh.Label!=l||g!=generation){key.Clear();feedback.Text="会话已切换，请重新打开卡片。";return;}
        if(!clear&&(u.Length==0)!=(k.Length==0)){feedback.Text="请同时填写 URL 和 Key，或恢复默认。";return;}
        var r=await Task.Run(()=>Store.Call(clear?"clear":"save",l,t,u,k));if(g!=generation)return;if(r.error!=null){feedback.Text=r.error;return;}
        saved=r.url??"";url.Text=saved;key.Text=r.key??"";Status();feedback.Text=clear||saved.Length==0?"已恢复使用 config.toml。":"已保存到本会话。";
    }catch{feedback.Text="保存失败，请重试。";}finally{if(g==generation){working=false;Arrange();}}}
    static string TierLabel(string tier){return tier=="priority"?"Fast":tier=="default"?"标准":tier??"由客户端决定";}
    void ShowSpeed(SpeedRecord r){
        if(r==null||r.error!=null||r.mode==null){speedReady=false;speed.Enabled=false;speedStatus.Text=r!=null&&r.error!=null?r.error:"速度设置暂时不可读。";return;}
        speedReady=true;string name=TierLabel(r.effectiveTier);speed.Text="\u26a1 "+(r.effectiveTier==null?"跟随":name);
        inherit.Checked=r.mode=="inherit";fast.Checked=r.mode=="priority";standard.Checked=r.mode=="default";
        string chosen=inherit.Checked?"跟随配置："+name:"本会话："+name;
        speed.AccessibleName="速度选择，"+chosen;speedTip.SetToolTip(speed,speed.AccessibleName);
        string last=r.lastStatus.HasValue?"上次请求："+(r.lastTier==null?"未指定档位":TierLabel(r.lastTier))+" · HTTP "+r.lastStatus:"尚无请求记录";
        speedStatus.Text=chosen+"\n"+last;speed.Enabled=ready&&!savingSpeed;
    }
    async Task ReadSpeed(){
        if(!ready||savingSpeed)return;int g=generation;string l=label,t=thread;lastSpeedRead=DateTime.UtcNow;
        var version=speedVersion;
        try{var r=await Task.Run(()=>Store.Speed("speed_read",l,t));if(g==generation&&version==speedVersion)ShowSpeed(r);}
        catch{if(g==generation&&version==speedVersion)ShowSpeed(null);}
    }
    int speedVersion;
    async Task ChangeSpeed(string mode){
        if(!ready||!speedReady||savingSpeed)return;int g=generation;string l=label,t=thread;speedVersion++;savingSpeed=true;speed.Enabled=false;
        try{var fresh=await Task.Run(()=>global::Anchor.Read(owner));if(g!=generation||fresh==null||fresh.Label!=l)return;
            var r=await Task.Run(()=>Store.Speed("speed_save",l,t,mode));if(g==generation)ShowSpeed(r);
        }catch{if(g==generation)ShowSpeed(null);}
        finally{if(g==generation){savingSpeed=false;lastSpeedRead=DateTime.UtcNow;speed.Enabled=ready&&speedReady;}}
    }
    int fontDpi;Font cardFont,titleFont;
    void Arrange(){canPlace=false;if(anchor==null)return;if(fontDpi!=dpi){var prev=cardFont;var pt=titleFont;cardFont=new Font("Microsoft YaHei UI",U(13),FontStyle.Regular,GraphicsUnit.Pixel);titleFont=new Font("Microsoft YaHei UI",U(14),FontStyle.Bold,GraphicsUnit.Pixel);Font=cardFont;heading.Font=titleFont;fontDpi=dpi;if(prev!=null)prev.Dispose();if(pt!=null)pt.Dispose();}
        int width=anchor.Card.Width,w=(int)Math.Round(width*96.0/dpi),y=anchor.Card.Bottom+U(9);int shift=options.Items.Count>0?32:0;
        int height=expanded?U(287+shift):U(48);
        if(y+height>anchor.Root.Bottom-U(5)){if(expanded && anchor.Card.Top-anchor.Root.Top>height+U(10))y=anchor.Card.Top-height-U(8);else if(y+height>anchor.Root.Bottom){if(Visible)Hide();return;}}
        canPlace=true;var rect=new Rectangle(anchor.Card.Left,y,width,height);if(Bounds!=rect){Bounds=rect;var path=new GraphicsPath();int r=U(16)*2;path.AddArc(0,0,r,r,180,90);path.AddArc(width-r,0,r,r,270,90);path.AddArc(width-r,height-r,r,r,0,90);path.AddArc(0,height-r,r,r,90,90);path.CloseFigure();var previous=Region;Region=new Region(path);path.Dispose();if(previous!=null)previous.Dispose();}
        int speedWidth=Math.Min(82,Math.Max(30,w/3));Place(heading,8,5,Math.Max(1,w-speedWidth-48),38);Place(speed,w-speedWidth-38,7,speedWidth,32);Place(fold,w-35,7,28,32);Place(subtitle,16,43,w-32,20);
        fold.Text=expanded?"−":"＋";fold.AccessibleName=expanded?"收起会话提供方":"展开会话提供方";
        foreach(Control c in new Control[]{subtitle,urlLabel,url,keyLabel,key,save,reset,feedback,speedStatus})c.Visible=expanded;options.Visible=expanded&&shift>0;
        Place(options,15,68,w-30,26);Place(urlLabel,16,68+shift,w-32,21);Place(url,16,91+shift,w-32,26);Place(keyLabel,16,122+shift,w-32,21);Place(key,16,145+shift,w-32,26);
        Place(save,16,183+shift,68,32);Place(reset,91,183+shift,90,32);Place(feedback,16,221+shift,w-32,20);Place(speedStatus,16,243+shift,w-32,38);save.Enabled=reset.Enabled=ready&&!working;url.Enabled=key.Enabled=ready&&!working;
    }
}
class Program {
    [STAThread] static void Main(){bool primary;using(var mutex=new Mutex(true,@"Local\ThreadProviderCardPublicV1",out primary)){if(!primary)return;try{Win.SetProcessDpiAwarenessContext(new IntPtr(-4));}catch{}Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);using(var card=new Card()){var handle=card.Handle;Application.Run();}}}
}
