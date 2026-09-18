// NiceWise components — shared JSX primitives.
// Attached to window so multiple <script> tags can share components.

const { useState } = React;

function MS({ name, size = 20, className = '', style = {} }) {
  return (
    <span className={`material-symbols-rounded ${className}`}
      style={{ fontSize: size, ...style }}>
      {name}
    </span>
  );
}

function Sidebar({ active, onSelect }) {
  const nav = [
    { id: 'home',        label: 'Home',        icon: 'home' },
    { id: 'inbox',       label: 'Inbox',       icon: 'inbox' },
    { id: 'tasks',       label: 'Tasks',       icon: 'task_alt' },
    { id: 'automations', label: 'Automations', icon: 'bolt' },
    { id: 'copilot',     label: 'Copilot',     icon: 'auto_awesome' },
  ];
  const secondary = [
    { id: 'analytics', label: 'Analytics', icon: 'analytics' },
    { id: 'settings',  label: 'Settings',  icon: 'settings' },
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">N</div>
        <div>NiceWise</div>
      </div>
      <nav className="nav">
        {nav.map(n => (
          <div key={n.id}
            className={`nav-item ${active === n.id ? 'active' : ''}`}
            onClick={() => onSelect(n.id)}>
            <MS name={n.icon} /> {n.label}
          </div>
        ))}
        <div className="nav-section">Workspace</div>
        {secondary.map(n => (
          <div key={n.id}
            className={`nav-item ${active === n.id ? 'active' : ''}`}
            onClick={() => onSelect(n.id)}>
            <MS name={n.icon} /> {n.label}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="avatar-sm">SL</div>
        <div className="you-meta">
          <div className="n">Sam Lee</div>
          <div className="r">Free plan</div>
        </div>
      </div>
    </aside>
  );
}

function Topbar({ title, subtitle }) {
  return (
    <div className="topbar">
      <div className="greeting">
        {title}
        {subtitle && <span className="sub">{subtitle}</span>}
      </div>
      <div className="search">
        <MS name="search" />
        <input placeholder="Find anything in NiceWise…" />
      </div>
    </div>
  );
}

function TaskRow({ title, meta, chip, done, onToggle }) {
  return (
    <div className={`task ${done ? 'done' : ''}`}>
      <div className="check" onClick={onToggle}>
        {done && <MS name="check" size={14} />}
      </div>
      <div className="title">{title}</div>
      {chip && <span className={`chip ${chip.tone || ''}`}>{chip.label}</span>}
      {meta && <div className="meta"><MS name="schedule" size={14} /> {meta}</div>}
    </div>
  );
}

function Chip({ children, tone }) {
  return <span className={`chip ${tone || ''}`}>{children}</span>;
}

function ProductIcon({ name }) {
  return (
    <div className="prod-icon">
      <img src={`../../assets/icons/product/${name}.png`} alt="" />
    </div>
  );
}

function Recipe({ steps, title, desc, enabled = true }) {
  return (
    <div className="recipe">
      <div className="flow">
        {steps.map((s, i) => (
          <React.Fragment key={i}>
            <span className="step"><MS name={s.icon} />{s.label}</span>
            {i < steps.length - 1 && <span className="arrow">→</span>}
          </React.Fragment>
        ))}
      </div>
      <div>
        <h4>{title}</h4>
        <p>{desc}</p>
      </div>
      <footer>
        <Chip tone={enabled ? 'success' : ''}>{enabled ? 'On' : 'Off'}</Chip>
        <button className="btn btn-ghost">Edit →</button>
      </footer>
    </div>
  );
}

function ChatMessage({ from, children }) {
  return (
    <div className={`msg ${from}`}>
      {from === 'ai' && <div className="avatar-ai">AI</div>}
      <div className="bubble">{children}</div>
    </div>
  );
}

Object.assign(window, { MS, Sidebar, Topbar, TaskRow, Chip, ProductIcon, Recipe, ChatMessage });
