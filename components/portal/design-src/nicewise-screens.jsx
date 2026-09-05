// NiceWise screens. Uses components from components.jsx (globals).

function HomeScreen() {
  return (
    <div className="screen">
      <Topbar title="Good afternoon, Sam" subtitle="Here's what's waiting for you today." />

      <div className="hero-card" style={{ marginBottom: 24 }}>
        <h2>Answers appear before you even search</h2>
        <p>Your week at a glance — seamless, connected, personal. Start with the three things that will actually move the needle.</p>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-onblue">Plan my day <MS name="arrow_forward" size={16} /></button>
          <button className="btn" style={{ background: 'rgba(255,255,255,0.18)', color: '#fff' }}>What changed?</button>
        </div>
      </div>

      <div className="grid-2">
        <div className="stack">
          <div className="card">
            <div className="hstack" style={{ justifyContent: 'space-between', marginBottom: 14 }}>
              <h3 style={{ margin: 0 }}>Today's focus</h3>
              <button className="btn btn-ghost">Add task <MS name="add" size={16} /></button>
            </div>
            <div>
              <TaskRow done title="Review Q3 pipeline summary" meta="9:00 AM" chip={{ label: 'Done', tone: 'success' }} />
              <TaskRow title="Prep slides for Monday review" meta="11:30 AM" chip={{ label: 'In progress', tone: 'blue' }} />
              <TaskRow title="Draft response to Cognigy integration brief" meta="2:00 PM" chip={{ label: 'Needs review', tone: 'warn' }} />
              <TaskRow title="1:1 with Priya — blockers" meta="4:00 PM" />
              <TaskRow title="Send weekly recap to team" meta="Later" chip={{ label: 'Later' }} />
            </div>
          </div>

          <div className="card warm">
            <h3>Suggested automations</h3>
            <p style={{ marginBottom: 16 }}>NiceWise spotted three things you do every week. Want to hand them off?</p>
            <div className="grid-3">
              <div className="card" style={{ padding: 14 }}>
                <ProductIcon name="schedule-blue" />
                <h4 style={{ margin: '10px 0 2px', fontSize: 14, fontWeight: 600 }}>Weekly recap</h4>
                <p style={{ fontSize: 12 }}>Every Friday, 4 PM</p>
              </div>
              <div className="card" style={{ padding: 14 }}>
                <ProductIcon name="ai-sparkle-blue" />
                <h4 style={{ margin: '10px 0 2px', fontSize: 14, fontWeight: 600 }}>Auto-summaries</h4>
                <p style={{ fontSize: 12 }}>After every meeting</p>
              </div>
              <div className="card" style={{ padding: 14 }}>
                <ProductIcon name="alerts-blue" />
                <h4 style={{ margin: '10px 0 2px', fontSize: 14, fontWeight: 600 }}>Blocker alerts</h4>
                <p style={{ fontSize: 12 }}>As soon as they appear</p>
              </div>
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="card dark">
            <div className="hstack" style={{ gap: 10, marginBottom: 12 }}>
              <div className="avatar-ai">AI</div>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.66)' }}>Copilot · just now</span>
            </div>
            <h3 style={{ color: '#fff' }}>Three things worth your attention</h3>
            <p>Priya mentioned a blocker on the Shine migration. The Q3 forecast shifted 4% since Monday. Your demo with NUG is 23 hours away.</p>
            <button className="btn btn-onblue" style={{ marginTop: 14 }}>Open Copilot →</button>
          </div>

          <div className="card">
            <h3>Recent files</h3>
            <div className="stack" style={{ gap: 8, marginTop: 10 }}>
              {[
                { name: 'Monday review — draft.nwise', meta: 'Edited 2m ago', icon: 'description' },
                { name: 'Q3 pipeline summary.pdf',     meta: '1 hour ago',   icon: 'picture_as_pdf' },
                { name: 'Cognigy brief.md',            meta: 'Yesterday',    icon: 'article' },
              ].map(f => (
                <div key={f.name} className="hstack" style={{ padding: '8px 10px', borderRadius: 12, background: 'var(--nice-warm-white)' }}>
                  <MS name={f.icon} size={18} style={{ color: 'var(--nice-blue)' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{f.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{f.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InboxScreen() {
  const items = [
    { from: 'Priya Shah',   subj: 'Re: Shine migration — quick blocker', time: '10:24 AM', unread: true  },
    { from: 'NiceWise AI',  subj: 'Summary ready for Monday review',     time: '9:51 AM',  unread: true, ai: true },
    { from: 'Maya Chen',    subj: 'Loved the draft — a few thoughts',    time: '9:12 AM' },
    { from: 'NUG team',     subj: 'Demo agenda, tomorrow 2pm',           time: 'Yesterday' },
    { from: 'Calendar',     subj: 'Your week reshuffled — 3 changes',    time: 'Yesterday' },
  ];
  return (
    <div className="screen">
      <Topbar title="Inbox" subtitle="Everything finds its way to one seamless place." />
      <div className="grid-2">
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {items.map((it, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: '16px 20px', borderBottom: i < items.length - 1 ? '1px solid var(--border-subtle)' : 0, alignItems: 'center', cursor: 'pointer' }}>
              <div className="avatar-sm" style={{ background: it.ai ? 'var(--gradient-indigo-blue)' : 'var(--nice-warm-white)', color: it.ai ? '#fff' : 'var(--nice-charcoal)' }}>
                {it.ai ? 'AI' : it.from.split(' ').map(w => w[0]).join('')}
              </div>
              <div style={{ flex: 1 }}>
                <div className="hstack" style={{ justifyContent: 'space-between' }}>
                  <div style={{ fontWeight: it.unread ? 600 : 500, fontSize: 14 }}>{it.from}</div>
                  <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{it.time}</div>
                </div>
                <div style={{ fontSize: 13, color: 'var(--fg-muted)', marginTop: 2, fontWeight: it.unread ? 500 : 300 }}>{it.subj}</div>
              </div>
              {it.unread && <div style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--nice-blue)' }} />}
            </div>
          ))}
        </div>

        <div className="card dark">
          <div className="hstack" style={{ gap: 10, marginBottom: 10 }}>
            <div className="avatar-ai">AI</div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.66)' }}>Inbox assistant</div>
          </div>
          <h3 style={{ color: '#fff' }}>You have 2 things that can't wait</h3>
          <p>Priya needs a decision on the Shine cutover by noon. NUG's demo prep is short two slides.</p>
          <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
            <button className="btn btn-onblue">Draft replies</button>
            <button className="btn" style={{ background: 'rgba(255,255,255,0.16)', color: '#fff' }}>Triage the rest</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TasksScreen() {
  const [tasks, setTasks] = useState([
    { id: 1, title: 'Review Q3 pipeline summary', col: 'done',  chip: { label: 'Done', tone: 'success' }, meta: '9:00 AM' },
    { id: 2, title: 'Prep slides for Monday review', col: 'doing', chip: { label: 'In progress', tone: 'blue' }, meta: '11:30 AM' },
    { id: 3, title: 'Draft Cognigy integration response', col: 'doing', chip: { label: 'Needs review', tone: 'warn' }, meta: '2:00 PM' },
    { id: 4, title: '1:1 with Priya — blockers', col: 'todo', meta: '4:00 PM' },
    { id: 5, title: 'Send weekly recap', col: 'todo', chip: { label: 'Later' }, meta: 'Fri 4 PM' },
    { id: 6, title: 'Ship Shine onboarding email', col: 'todo', meta: 'Next week' },
  ]);
  const cols = [
    { id: 'todo',  title: 'To do'       },
    { id: 'doing', title: 'In progress' },
    { id: 'done',  title: 'Done'        },
  ];
  return (
    <div className="screen">
      <Topbar title="Tasks" subtitle="Things get booked, sorted, done." />
      <div className="hstack" style={{ justifyContent: 'space-between', marginBottom: 18 }}>
        <div className="hstack" style={{ gap: 8 }}>
          <Chip tone="blue">This week</Chip>
          <Chip>Everything</Chip>
          <Chip>Assigned to me</Chip>
        </div>
        <button className="btn btn-primary">New task <MS name="add" size={16} /></button>
      </div>

      <div className="grid-3">
        {cols.map(c => (
          <div key={c.id} className="card warm" style={{ padding: 16 }}>
            <div className="hstack" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{c.title}</h4>
              <span className="chip">{tasks.filter(t => t.col === c.id).length}</span>
            </div>
            {tasks.filter(t => t.col === c.id).map(t => (
              <div key={t.id} className="card" style={{ padding: 12, marginBottom: 8 }}>
                <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6, textDecoration: t.col === 'done' ? 'line-through' : 'none', color: t.col === 'done' ? 'var(--fg-subtle)' : 'inherit' }}>{t.title}</div>
                <div className="hstack" style={{ justifyContent: 'space-between' }}>
                  {t.chip ? <Chip tone={t.chip.tone}>{t.chip.label}</Chip> : <span />}
                  {t.meta && <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>{t.meta}</div>}
                </div>
              </div>
            ))}
            {c.id === 'todo' && (
              <button className="btn btn-ghost" style={{ padding: '6px 10px', fontSize: 13 }}>+ Add a task</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AutomationsScreen() {
  return (
    <div className="screen">
      <Topbar title="Automations" subtitle="Let NiceWise handle the hundred small things." />
      <div className="hstack" style={{ justifyContent: 'space-between', marginBottom: 18 }}>
        <div className="hstack" style={{ gap: 8 }}>
          <Chip tone="blue">Running</Chip>
          <Chip>Paused</Chip>
          <Chip>Templates</Chip>
        </div>
        <button className="btn btn-primary">Build an automation <MS name="auto_awesome" size={16} /></button>
      </div>

      <div className="grid-3">
        <Recipe title="Meeting recap → email"
          desc="After every meeting, draft a summary and send to attendees."
          steps={[
            { icon: 'videocam',   label: 'Meeting ends' },
            { icon: 'auto_awesome', label: 'Summarize' },
            { icon: 'mail',       label: 'Email team' },
          ]} />
        <Recipe title="Blocker → Priya"
          desc="When someone posts a blocker, ping Priya in the right channel."
          steps={[
            { icon: 'chat_bubble', label: 'Blocker mentioned' },
            { icon: 'bolt',        label: 'Classify' },
            { icon: 'forward',     label: 'Notify Priya' },
          ]} />
        <Recipe title="Weekly recap" enabled={false}
          desc="Every Friday afternoon, summarize the week and share with the team."
          steps={[
            { icon: 'event',      label: 'Friday, 4 PM' },
            { icon: 'auto_awesome', label: 'Recap the week' },
            { icon: 'send',       label: 'Share to #team' },
          ]} />
        <Recipe title="Demo prep"
          desc="24 hours before a demo, pull the latest deck and flag missing content."
          steps={[
            { icon: 'schedule', label: 'T-24h' },
            { icon: 'search',   label: 'Find deck' },
            { icon: 'flag',     label: 'Flag gaps' },
          ]} />
        <Recipe title="Customer quote watch" enabled={false}
          desc="Whenever a customer mentions NiCE in a transcript, save the quote."
          steps={[
            { icon: 'mic',   label: 'Transcript' },
            { icon: 'search', label: 'Detect mention' },
            { icon: 'bookmark', label: 'Save quote' },
          ]} />
        <div className="recipe" style={{ background: 'var(--gradient-indigo-blue)', color: '#fff', alignItems: 'flex-start', justifyContent: 'center' }}>
          <MS name="auto_awesome" size={28} />
          <div>
            <h4 style={{ color: '#fff' }}>Build your own</h4>
            <p style={{ color: 'rgba(255,255,255,0.85)' }}>Describe the outcome in plain English. NiceWise wires the steps.</p>
          </div>
          <button className="btn btn-onblue">Start with a sentence →</button>
        </div>
      </div>
    </div>
  );
}

function CopilotScreen() {
  const [msg, setMsg] = useState('');
  return (
    <div className="screen">
      <Topbar title="Copilot" subtitle="Ask anything. Get the real answer." />
      <div className="grid-2">
        <div className="card" style={{ padding: 22, minHeight: 520, display: 'flex', flexDirection: 'column' }}>
          <div className="chat" style={{ flex: 1 }}>
            <ChatMessage from="ai">Morning, Sam. Three things worth your attention today — blocker on the Shine migration, the Q3 forecast shifted 4%, and the NUG demo is 23 hours away. Where do you want to start?</ChatMessage>
            <ChatMessage from="me">Start with the forecast — what moved?</ChatMessage>
            <ChatMessage from="ai">Two deals slipped from Q3 into Q4: Everbright (€420K) and Monarch Retail ($310K). Upside from Cognigy partnerships made up 1.8 points. I can put the detail in a slide or give you talking points. Which?</ChatMessage>
            <ChatMessage from="me">Talking points, please.</ChatMessage>
            <ChatMessage from="ai">On it. Drafting three concise points with the numbers attached — back in a few seconds.</ChatMessage>
          </div>
          <div className="search" style={{ width: 'auto', marginTop: 14, background: 'var(--nice-warm-white)', borderRadius: 999, padding: '10px 16px' }}>
            <MS name="auto_awesome" style={{ color: 'var(--nice-blue)' }} />
            <input placeholder="Ask anything…" value={msg} onChange={e => setMsg(e.target.value)} />
            <button className="btn btn-primary" style={{ padding: '8px 14px', fontSize: 13 }}>Send <MS name="arrow_forward" size={14} /></button>
          </div>
        </div>

        <div className="stack">
          <div className="card warm">
            <div className="section-title">Try asking</div>
            {[
              "What's changed since Monday?",
              'Summarize my last 3 customer calls',
              'Who is blocked, and on what?',
              "Draft Friday's team recap",
            ].map(s => (
              <div key={s} className="hstack" style={{ padding: '10px 12px', borderRadius: 10, background: '#fff', marginBottom: 6, cursor: 'pointer', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{s}</span>
                <MS name="arrow_forward" size={16} style={{ color: 'var(--fg-subtle)' }} />
              </div>
            ))}
          </div>
          <div className="card grad-emerald">
            <div style={{ fontSize: 12, fontWeight: 500, opacity: 0.88, marginBottom: 6 }}>Copilot memory</div>
            <h3 style={{ color: '#fff' }}>It remembers what matters to you</h3>
            <p>Your team, your deals, your priorities — all context carried forward, never repeated back.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function AnalyticsScreen() {
  return (
    <div className="screen">
      <Topbar title="Analytics" subtitle="How your week actually went." />
      <div className="grid-3">
        {[
          { label: 'Tasks closed',   value: '12', delta: '+3 vs last week', tone: 'success' },
          { label: 'Automations run', value: '47', delta: 'saved ~4.2 h', tone: 'blue' },
          { label: 'Focus time',     value: '9.5 h', delta: '+1.1 h', tone: 'success' },
        ].map(k => (
          <div key={k.label} className="card">
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', fontWeight: 500 }}>{k.label}</div>
            <div style={{ fontSize: 38, fontWeight: 600, letterSpacing: '-0.028em', margin: '6px 0' }}>{k.value}</div>
            <Chip tone={k.tone}>{k.delta}</Chip>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 18 }}>
        <h3>Where your week went</h3>
        <p style={{ marginBottom: 16 }}>A rough breakdown across meetings, focused work, and automated tasks.</p>
        <div style={{ display: 'flex', height: 28, borderRadius: 999, overflow: 'hidden', background: 'var(--nice-warm-white)' }}>
          <div style={{ width: '42%', background: 'var(--nice-blue)' }} />
          <div style={{ width: '28%', background: 'var(--electric-indigo)' }} />
          <div style={{ width: '16%', background: 'var(--teal)' }} />
          <div style={{ width: '14%', background: 'var(--emerald)' }} />
        </div>
        <div className="hstack" style={{ gap: 16, marginTop: 12, flexWrap: 'wrap', fontSize: 13 }}>
          <div className="hstack" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--nice-blue)' }} /> Focused work 42%</div>
          <div className="hstack" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--electric-indigo)' }} /> Meetings 28%</div>
          <div className="hstack" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--teal)' }} /> Automations 16%</div>
          <div className="hstack" style={{ gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: 'var(--emerald)' }} /> Admin 14%</div>
        </div>
      </div>
    </div>
  );
}

function SettingsScreen() {
  return (
    <div className="screen">
      <Topbar title="Settings" />
      <div className="card" style={{ maxWidth: 680 }}>
        <h3>You</h3>
        <div className="stack" style={{ marginTop: 12 }}>
          {[
            { l: 'Name', v: 'Sam Lee' },
            { l: 'Email', v: 'sam@example.com' },
            { l: 'Workspace', v: 'NiCErs' },
            { l: 'Role', v: 'Member' },
          ].map(r => (
            <div key={r.l} className="hstack" style={{ justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>{r.l}</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{r.v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [active, setActive] = useState(() => localStorage.getItem('nw-screen') || 'home');
  const go = id => { setActive(id); localStorage.setItem('nw-screen', id); };
  const map = {
    home: HomeScreen, inbox: InboxScreen, tasks: TasksScreen,
    automations: AutomationsScreen, copilot: CopilotScreen,
    analytics: AnalyticsScreen, settings: SettingsScreen,
  };
  const Screen = map[active] || HomeScreen;
  return (
    <div id="app-root">
      <Sidebar active={active} onSelect={go} />
      <main className="main" data-screen-label={active}>
        <Screen />
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
