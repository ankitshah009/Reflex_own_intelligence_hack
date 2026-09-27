import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, ArrowUpRight, BookOpen, Check, CheckCheck, ChevronDown, ChevronRight, Circle, CircleAlert, CircleCheck, Code2, Command, Copy, Database, ExternalLink, FlaskConical, GitBranch, GitCommitHorizontal, GitPullRequest, Layers3, LoaderCircle, Menu, MessageSquare, Play, Plus, Radio, RotateCcw, Settings2, ShieldCheck, Sparkles, Terminal, Unplug, X, Zap } from 'lucide-react';
import { api, post } from './api';
import { EMPTY_STATE } from './types';
import type { Checkpoint, Condition, Decision, Evaluation, Experience, Job, Sample, Screen, State, Trajectory } from './types';

const NAV: { id: Screen; label: string; icon: typeof Code2; subtitle: string }[] = [
  { id: 'review', label: 'Review workspace', icon: GitPullRequest, subtitle: 'Work & correct' },
  { id: 'experience', label: 'Experience library', icon: Layers3, subtitle: 'Your learning signal' },
  { id: 'learn', label: 'Learning studio', icon: Zap, subtitle: 'Experience → weights' },
  { id: 'replay', label: 'Evaluation lab', icon: FlaskConical, subtitle: 'Measure what changed' },
];
const TITLES: Record<Screen, { eyebrow: string; title: string; description: string }> = {
  review: { eyebrow: 'THE EXPERIENCE LAYER', title: 'Good judgment starts with experience.', description: 'Review a change. Make a correction. Give your next review a better starting point.' },
  experience: { eyebrow: 'YOUR COLLECTIVE EXPERIENCE', title: 'Every correction has a future.', description: 'A durable record of the work, the decision, and the feedback worth learning from.' },
  learn: { eyebrow: 'THE LEARNING LAYER', title: 'Turn experience into intelligence.', description: 'Train a specialist on your engineering judgment. Keep the checkpoint. Own the improvement.' },
  replay: { eyebrow: 'THE PROOF', title: 'The prompt stayed. Did the model change?', description: 'Compare base, memory, and learned weights on the same held-out pull requests.' },
};
const TERMINAL_STATUS = new Set(['completed', 'complete', 'succeeded', 'success', 'done', 'failed', 'error', 'cancelled', 'interrupted']);
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const dateText = (value?: string) => value ? new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'Just now';
const contextText = (value: unknown): string => typeof value === 'string' ? value : Array.isArray(value) ? value.map(contextText).join('; ') : value && typeof value === 'object' ? Object.entries(value).map(([key, item]) => `${key.replace(/_/g, ' ')}: ${contextText(item)}`).join('; ') : typeof value === 'boolean' ? value ? 'Yes' : 'No' : value == null ? '' : String(value);
const ISSUE_LABELS: Record<string, string> = { broad_exception: 'Catch-all exception', missing_regression_test: 'Missing regression test', sql_injection: 'SQL injection', missing_timeout: 'Missing timeout', secret_exposure: 'Secret exposure', missing_authorization: 'Missing authorization', path_traversal: 'Path traversal', mutable_default: 'Mutable default', race_condition: 'Race condition', unsafe_deserialization: 'Unsafe deserialization', event_loop_blocking: 'Event loop blocking', missing_input_validation: 'Missing validation', resource_leak: 'Resource leak', idempotency_violation: 'Idempotency violation', error_contract_violation: 'Error contract violation' };
const shortId = (value: string) => value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
const conditionName = (value: Condition) => ({ base: 'Base model', memory: 'With memory', learned: 'Learned weights' }[value]);

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? 'compact' : ''}`}><div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>{!compact && <><span>reflex<span className="brand-dot">.</span></span><span className="brand-beta">LAB</span></>}</div>;
}
function StatusDot({ ready }: { ready: boolean }) { return <span className={`status-dot ${ready ? 'ready' : ''}`} />; }
function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'blue' | 'red' | 'green' | 'amber' }) { return <span className={`pill pill-${tone}`}>{children}</span>; }
function Empty({ icon: Icon, title, description, action }: { icon: typeof Code2; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={24} strokeWidth={1.6} /></div><h3>{title}</h3><p>{description}</p>{action}</div>;
}
function LoadingButton({ busy, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return <button {...props} disabled={busy || props.disabled}>{busy && <LoaderCircle size={16} className="spin" />}{children}</button>;
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('review');
  const [state, setState] = useState<State>(EMPTY_STATE);
  const [loaded, setLoaded] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [connectionsOpen, setConnectionsOpen] = useState(false);
  const closeConnections = useCallback(() => setConnectionsOpen(false), []);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>('');
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<Trajectory[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const jobType = useRef('');
  const selected = state.experiences.find(item => item.id === selectedId);
  const riverReady = !!state.status.river?.configured;
  const busy = submitting || !!(activeJob && !TERMINAL_STATUS.has(activeJob.status));

  const refresh = useCallback(async () => {
    try {
      const next = await api<State>('/state');
      setState({ ...EMPTY_STATE, ...next, stats: { ...EMPTY_STATE.stats, ...next.stats } });
      setLoaded(true); setConnectionError(''); return next;
    } catch (err) { setLoaded(true); setConnectionError(errorText(err)); return null; }
  }, []);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 6000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => { if (activeJob && !TERMINAL_STATUS.has(activeJob.status)) return; const job = state.jobs.find(item => !TERMINAL_STATUS.has(item.status)); if (job) { jobType.current = job.kind || job.type || ''; setActiveJob({ ...job, type: job.kind || job.type }); setEvents(job.events || []); } }, [state.jobs, activeJob]);
  useEffect(() => { if (!mobileOpen) return; const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setMobileOpen(false); }; document.addEventListener('keydown', close); return () => document.removeEventListener('keydown', close); }, [mobileOpen]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 4500); return () => window.clearTimeout(timer); }, [toast]);

  useEffect(() => {
    if (!activeJob || TERMINAL_STATUS.has(activeJob.status)) return;
    let stopped = false;
    let polling = false;
    const id = activeJob.id;
    const source = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
    const receive = (event: MessageEvent) => {
      try {
        const item = JSON.parse(event.data) as Trajectory & { status?: string };
        if (item.message) setEvents(existing => [...existing, { ...item, timestamp: item.timestamp || new Date().toISOString() }].slice(-80));
      } catch { /* Polling remains the durable source of truth. */ }
    };
    source.onmessage = receive;
    ['progress', 'log', 'status', 'complete', 'error'].forEach(type => source.addEventListener(type, receive as EventListener));
    const poll = async () => {
      if (polling || stopped) return;
      polling = true;
      try {
        const job = await api<Job>(`/jobs/${encodeURIComponent(id)}`);
        if (stopped) return;
        setActiveJob({ ...job, id: job.id || id, type: job.kind || job.type || jobType.current });
        if (TERMINAL_STATUS.has(job.status)) {
          source.close();
          const updated = await refresh();
          if (job.status === 'failed' || job.status === 'error' || job.status === 'interrupted') setError(typeof job.error === 'string' ? job.error : job.error?.message || 'The operation failed. Check your connection settings and try again.');
          else if (job.status !== 'cancelled') {
            if (jobType.current === 'review' && updated?.experiences[0]) {
              const result = job.result as { id?: string; experience_id?: string } | undefined;
              setSelectedId(result?.experience_id || result?.id || updated.experiences[0].id);
            }
            setToast(jobType.current === 'training' ? 'Training completed. Your checkpoint is ready.' : jobType.current === 'evaluation' ? 'Evaluation completed. Measured results are ready.' : 'Review complete. Add your judgment.');
          }
        }
      } catch (err) { if (!stopped) setError(errorText(err)); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1800);
    return () => { stopped = true; source.close(); window.clearInterval(timer); };
  }, [activeJob?.id, !!activeJob && TERMINAL_STATUS.has(activeJob.status), refresh]);

  const startJob = async (path: string, body: unknown, type: string) => {
    if (busy) return;
    setSubmitting(true); setError(''); setEvents([]); jobType.current = type;
    try { const response = await post<{ job_id: string }>(path, body); setActiveJob({ id: response.job_id, status: 'queued', type }); }
    catch (err) { setError(errorText(err)); }
    finally { setSubmitting(false); }
  };
  const changeScreen = (next: Screen) => { setScreen(next); setMobileOpen(false); setError(''); };
  const title = TITLES[screen];
  const total = state.stats.experiences;

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside id="main-navigation" className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`} aria-label="Main navigation">
      <Brand />
      <div className="workspace-switcher"><div className="workspace-icon"><Code2 size={16}/></div><div><strong>Engineering judgment</strong><span>Personal workspace</span></div><ChevronDown size={14}/></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav>{NAV.map(item => <button key={item.id} className={`nav-item ${screen === item.id ? 'active' : ''}`} onClick={() => changeScreen(item.id)} aria-current={screen === item.id ? 'page' : undefined}><item.icon size={19} strokeWidth={1.7}/><span>{item.label}</span>{item.id === 'experience' && total > 0 && <span className="nav-count">{total}</span>}{screen === item.id && <span className="nav-active-mark"/>}</button>)}</nav>
      <div className="sidebar-note"><div className="orbit-mini" aria-hidden="true"><Circle size={35}/><GitCommitHorizontal size={24}/></div><h3>Your work, compounded.</h3><p>Experience becomes a model that carries your judgment forward.</p><button onClick={() => changeScreen('learn')}>See the learning loop <ArrowUpRight size={14}/></button></div>
      <div className="sidebar-bottom"><button className="connection-button" onClick={() => setConnectionsOpen(true)}><Settings2 size={18}/><span>Connections</span><StatusDot ready={riverReady}/></button><div className="profile"><div className="avatar">Y</div><div><strong>Personal workspace</strong><span>Saved on this device</span></div><span className="profile-ellipsis">···</span></div></div>
    </aside>
    {mobileOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)}/>}
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="mobile-menu icon-button" aria-label="Open navigation" aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen(true)}><Menu size={20}/></button><span>Workspace</span><ChevronRight size={13}/><strong>{NAV.find(item => item.id === screen)?.label}</strong></div><div className="topbar-right"><span className="local-badge"><span/>LOCAL WORKSPACE</span><button className="connection-status" onClick={() => setConnectionsOpen(true)}><StatusDot ready={riverReady}/>{state.status.river?.verified ? 'River connected' : riverReady ? 'River key detected' : 'Connect River'}<ChevronRight size={13}/></button></div></header>
      <main id="main-content">
        <div className="page-heading"><div><div className="eyebrow"><span/>{title.eyebrow}</div><h1>{title.title}</h1><p>{title.description}</p></div><div className="heading-emblem" aria-hidden="true"><GitBranch size={46} strokeWidth={1}/></div></div>
        {connectionError && <div className="banner banner-error" role="alert"><CircleAlert size={18}/><div><strong>Backend unavailable</strong><p>{connectionError}</p></div><button className="text-button" onClick={() => void refresh()}>Reconnect <RotateCcw size={14}/></button></div>}
        {error && <div className="banner banner-error" role="alert"><CircleAlert size={18}/><p>{error}</p><button className="icon-button" aria-label="Dismiss error" onClick={() => setError('')}><X size={17}/></button></div>}
        <Lineage stats={state.stats} checkpoints={state.checkpoints.length} screen={screen} onNavigate={changeScreen}/>
        {!loaded ? <div className="workspace-loading"><LoaderCircle size={23} className="spin"/><span>Opening your workspace…</span></div> : <>
          {screen === 'review' && <ReviewWorkspace samples={state.samples} selected={selected} experiences={state.experiences} checkpoints={state.checkpoints} riverReady={riverReady} busy={busy} events={events} activeJob={activeJob} onSelect={setSelectedId} onConnect={() => setConnectionsOpen(true)} onReview={body => void startJob('/reviews', body, 'review')} onFeedback={async (body, currentId) => { setError(''); try { const result = await post<Experience>(currentId ? `/experiences/${encodeURIComponent(currentId)}/feedback` : '/experiences/manual', body); await refresh(); setSelectedId(result.id); setToast('Feedback saved. One more experience to learn from.'); return true; } catch (err) { setError(errorText(err)); return false; } }}/>} 
          {screen === 'experience' && <ExperienceLibrary experiences={state.experiences} eligible={state.stats.eligible} onSelect={id => { setSelectedId(id); changeScreen('review'); }} onReview={() => { setSelectedId(''); changeScreen('review'); }} onLearn={() => changeScreen('learn')}/>}
          {screen === 'learn' && <LearningStudio state={state} riverReady={riverReady} busy={busy} activeJob={activeJob} events={events} onConnect={() => setConnectionsOpen(true)} onTrain={body => void startJob('/training', body, 'training')} onReview={() => changeScreen('review')} onReplay={() => changeScreen('replay')}/>}
          {screen === 'replay' && <EvaluationLab evaluations={state.evaluations} checkpoints={state.checkpoints} riverReady={riverReady} busy={busy} activeJob={activeJob} events={events} onConnect={() => setConnectionsOpen(true)} onEvaluate={checkpoint => void startJob('/evaluations', { checkpoint }, 'evaluation')} onLearn={() => changeScreen('learn')}/>}
        </>}
        <footer className="page-footer"><span><Brand compact/>Experience → Intelligence</span><span>UFO works. River learns. You own it.</span></footer>
      </main>
    </div>
    {connectionsOpen && <Connections riverReady={riverReady} riverVerified={!!state.status.river?.verified} ufoReady={!!state.status.ufo?.configured} model={state.status.river?.model} onClose={closeConnections} onRefresh={refresh}/>}
    {toast && <div className="toast" role="status"><CircleCheck size={18}/>{toast}<button className="icon-button" aria-label="Dismiss notification" onClick={() => setToast('')}><X size={14}/></button></div>}
  </div>;
}

function Lineage({ stats, checkpoints, screen, onNavigate }: { stats: State['stats']; checkpoints: number; screen: Screen; onNavigate: (screen: Screen) => void }) {
  const steps: { screen: Screen; icon: typeof Code2; title: string; detail: string; number: string }[] = [
    { screen: 'review', icon: GitPullRequest, title: 'Do the work', detail: 'A real review, captured', number: '01' },
    { screen: 'experience', icon: MessageSquare, title: 'Collect experience', detail: `${stats.experiences} saved · ${stats.corrections} judgments`, number: '02' },
    { screen: 'learn', icon: Zap, title: 'Learn the judgment', detail: `${stats.eligible} examples ready`, number: '03' },
    { screen: 'replay', icon: ShieldCheck, title: 'Prove the improvement', detail: `${checkpoints} ${checkpoints === 1 ? 'checkpoint' : 'checkpoints'} to evaluate`, number: '04' },
  ];
  return <div className="lineage" aria-label="Experience to intelligence workflow">{steps.map((step, index) => <button key={step.screen} className={`lineage-step ${screen === step.screen ? 'current' : ''}`} onClick={() => onNavigate(step.screen)}><span className="lineage-icon"><step.icon size={18} strokeWidth={1.8}/></span><span className="lineage-text"><strong>{step.title}</strong><span>{step.detail}</span></span><span className="lineage-number">{step.number}</span>{index < 3 && <ChevronRight className="lineage-arrow" size={15}/>}</button>)}</div>;
}

type Draft = { title: string; repo: string; context: string; diff: string };
function ReviewWorkspace({ samples, selected, experiences, checkpoints, riverReady, busy, events, activeJob, onSelect, onConnect, onReview, onFeedback }: {
  samples: Sample[]; selected?: Experience; experiences: Experience[]; checkpoints: Checkpoint[]; riverReady: boolean; busy: boolean; events: Trajectory[]; activeJob: Job | null; onSelect: (id: string) => void; onConnect: () => void; onReview: (body: unknown) => void; onFeedback: (body: unknown, id?: string) => Promise<boolean>;
}) {
  const [sampleId, setSampleId] = useState('');
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState<Draft>({ title: '', repo: '', context: '', diff: '' });
  const [tab, setTab] = useState<'diff' | 'activity'>('diff');
  const [condition, setCondition] = useState<Condition>('base');
  const [checkpoint, setCheckpoint] = useState('');
  const sample = samples.find(item => item.id === sampleId) || samples.find(item => item.split !== 'eval' && item.split !== 'test') || samples[0];
  const current = selected || (custom ? draft : sample);
  const review = selected?.agent_review;
  const activity = busy && activeJob?.type === 'review' ? events : selected?.trajectory || [];
  const reviewBusy = busy && (!activeJob || activeJob.type === 'review');
  const availableSamples = samples.filter(item => item.split !== 'eval' && item.split !== 'test' && item.split !== 'held_out');
  const submit = () => {
    if (!current?.diff.trim() || !current.title.trim()) return;
    onReview({ title: current.title, diff: current.diff, repo: current.repo || '', context: current.context || '', condition, ...(condition === 'learned' ? { checkpoint: checkpoint || checkpoints[0]?.checkpoint || checkpoints[0]?.id } : {}) }); setTab('activity');
  };
  return <div className="review-layout">
    <section className="review-main">
      <div className="panel review-panel"><div className="panel-title"><div><GitPullRequest size={18}/><h2>Review a pull request</h2></div><button className="text-button" onClick={() => { onSelect(''); setCustom(!custom); setTab('diff'); }}>{custom ? <BookOpen size={14}/> : <Plus size={14}/>} {custom ? 'Use a sample' : 'Your own diff'}</button></div>
        <div className="review-controls">
          {selected ? <div className="selected-experience"><Pill tone="blue">SAVED EXPERIENCE</Pill><button className="text-button" onClick={() => { onSelect(''); setTab('diff'); }}>New review <Plus size={14}/></button></div> : custom ? <div className="custom-fields"><label>Pull request title<input value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} placeholder="Handle failed payment attempts"/></label><label>Repository<input value={draft.repo} onChange={event => setDraft({ ...draft, repo: event.target.value })} placeholder="team/payments-service"/></label></div> : <><label className="field-label" htmlFor="sample-select">START WITH A PRACTICE CHANGE</label><div className="select-wrap"><GitBranch size={16}/><select id="sample-select" value={sample?.id || ''} onChange={event => { setSampleId(event.target.value); onSelect(''); }}><option value="" disabled>{availableSamples.length ? 'Select a pull request' : 'No sample changes available'}</option>{availableSamples.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select><ChevronDown size={16}/></div></>}
          {current && !custom && <div className="pr-meta"><span><GitBranch size={13}/>{current.repo || 'Local repository'}</span><span className="meta-divider"/><span>{selected ? `Experience ${shortId(selected.id)}` : 'Sample context · no model result yet'}</span></div>}
          {(selected || custom) && <h3 className="pr-title">{selected?.title}</h3>}
          {custom && !selected ? <label className="context-input">Relevant context<textarea rows={2} value={draft.context} onChange={event => setDraft({ ...draft, context: event.target.value })} placeholder="What changed, why it changed, and any relevant test output…"/></label> : current?.context && <RepositoryContext context={current.context}/>}
        </div>
        <div className="code-tabs"><div role="tablist" aria-label="Review context"><button role="tab" aria-selected={tab === 'diff'} className={tab === 'diff' ? 'selected' : ''} onClick={() => setTab('diff')}><Code2 size={15}/>Code changes</button><button role="tab" aria-selected={tab === 'activity'} className={tab === 'activity' ? 'selected' : ''} onClick={() => setTab('activity')}><Activity size={15}/>Agent activity{reviewBusy && <span className="tiny-pulse"/>}{activity.length > 0 && <span className="tab-count">{activity.length}</span>}</button></div><span className="read-only-label">{custom && !selected ? 'EDITABLE' : 'READ ONLY'}</span></div>
        <div role="tabpanel" className={tab === 'diff' ? 'code-area' : 'activity-area'}>
          {tab === 'diff' ? custom && !selected ? <textarea className="diff-editor" spellCheck={false} aria-label="Paste your unified diff" value={draft.diff} onChange={event => setDraft({ ...draft, diff: event.target.value })} placeholder={'Paste a unified diff here…\n\ndiff --git a/service.py b/service.py\n--- a/service.py\n+++ b/service.py'}/> : current?.diff ? <DiffViewer diff={current.diff}/> : <div className="code-empty"><Code2 size={30}/><p>Select a sample or paste a diff to begin.</p></div> : <ActivityFeed events={activity} busy={reviewBusy}/>}
        </div>
        <div className="review-action-bar"><div className="model-picker"><span className="field-label">REVIEWER</span><div className="small-select"><select aria-label="Reviewer condition" value={condition} onChange={event => setCondition(event.target.value as Condition)}><option value="base">Base model</option><option value="memory">With saved memory</option><option value="learned" disabled={!checkpoints.length}>Learned specialist</option></select><ChevronDown size={12}/></div>{condition === 'learned' && <select className="checkpoint-select" aria-label="Reviewer checkpoint" value={checkpoint || checkpoints[0]?.checkpoint || checkpoints[0]?.id} onChange={event => setCheckpoint(event.target.value)}>{checkpoints.map(item => <option key={item.id} value={item.checkpoint || item.id}>{item.name}</option>)}</select>}</div>{riverReady ? <LoadingButton className="button button-primary" busy={reviewBusy} disabled={busy || !current?.diff.trim() || !current?.title.trim()} onClick={submit}>{!reviewBusy && <Play size={15} fill="currentColor"/>}{reviewBusy ? 'Reviewing…' : selected ? 'Review again' : 'Run review'}{!reviewBusy && <ArrowRight size={16}/>}</LoadingButton> : <button className="button button-primary" onClick={onConnect}><Unplug size={16}/>Connect River<ArrowUpRight size={15}/></button>}</div>
      </div>
      {review && <div className="panel verdict-panel"><div className="panel-title"><div><Sparkles size={17}/><h2>Agent review</h2></div><Pill tone={review.decision === 'REJECT' ? 'red' : 'green'}>{review.decision === 'REJECT' ? <CircleAlert size={12}/> : <Check size={12}/>}{review.decision}</Pill></div><div className="verdict-body"><p>{review.summary || 'Review completed.'}</p>{review.issues?.map((issue, index) => <div className="review-issue" key={`${issue.tag || issue.title}-${index}`}><span className="issue-number">{index + 1}</span><div><strong>{issue.title || ISSUE_LABELS[issue.tag] || issue.tag}</strong>{(issue.detail || issue.message) && <p>{issue.detail || issue.message}</p>}</div>{issue.severity && <Pill tone="amber">{issue.severity}</Pill>}</div>)}</div></div>}
      {!review && !riverReady && <div className="connection-hint"><div className="hint-icon"><Unplug size={18}/></div><div><strong>Your first review starts with a connection.</strong><p>Connect River to run the specialist. You can label a change now to begin collecting training examples.</p></div><button className="text-button" onClick={onConnect}>Set up <ArrowUpRight size={14}/></button></div>}
    </section>
    <aside className="review-aside"><FeedbackPanel selected={selected} current={current} onSave={onFeedback}/><div className="panel recent-panel"><div className="panel-title"><div><GitCommitHorizontal size={17}/><h2>Recent experiences</h2></div><span className="subtle-count">{experiences.length}</span></div>{experiences.length ? <div className="recent-list">{experiences.slice(0, 5).map(item => <button key={item.id} className={`recent-item ${selected?.id === item.id ? 'selected' : ''}`} onClick={() => { onSelect(item.id); setTab('diff'); }}><span className={`recent-mark ${item.human_feedback ? 'labeled' : ''}`}>{item.human_feedback ? <Check size={12}/> : <GitPullRequest size={12}/>}</span><span><strong>{item.title}</strong><small>{item.human_feedback ? 'Human judgment captured' : 'Ready for your feedback'}</small></span><ChevronRight size={14}/></button>)}</div> : <div className="recent-empty"><div className="empty-timeline" aria-hidden="true"><span/><i/><span/><i/><span/></div><p>Your experience starts here.</p><small>Completed reviews and corrections appear as you work.</small></div>}</div><div className="aside-footnote"><ShieldCheck size={15}/><span>Feedback is stored in your local workspace. Training only starts when you choose.</span></div></aside>
  </div>;
}

function RepositoryContext({ context }: { context: string | Record<string, unknown> }) {
  if (typeof context === 'string') return <p className="context-text">{context}</p>;
  const conventions = Array.isArray(context.engineering_conventions) ? context.engineering_conventions : [];
  const changeType = typeof context.change_type === 'string' ? ({ bugfix: 'Bug fix', feature: 'Feature', refactor: 'Refactor' }[context.change_type] || context.change_type.replace(/_/g, ' ')) : '';
  const other = Object.entries(context).filter(([key]) => !['fictional', 'change_type', 'engineering_conventions', 'test_evidence'].includes(key));
  return <div className="repository-context">
    <div className="context-overview">{changeType && <Pill>{changeType}</Pill>}{context.test_evidence != null && <p>{contextText(context.test_evidence)}</p>}</div>
    {(conventions.length > 0 || other.length > 0) && <details className="context-details"><summary><BookOpen size={13}/>Repository context{conventions.length > 0 && <span>{conventions.length} conventions</span>}<ChevronDown size={13}/></summary><div>{conventions.length > 0 && <ul>{conventions.map((item, index) => <li key={index}>{contextText(item)}</li>)}</ul>}{other.map(([key, value]) => <p key={key}><strong>{key.replace(/_/g, ' ')}: </strong>{contextText(value)}</p>)}</div></details>}
  </div>;
}

function DiffViewer({ diff }: { diff: string }) {
  let oldLine = 0, newLine = 0;
  return <div className="diff-viewer" tabIndex={0} aria-label="Code diff">{diff.split('\n').map((line, index) => {
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    const header = /^(diff --git|index |--- |\+\+\+ )/.test(line);
    let oldNo: number | string = '', newNo: number | string = '', kind = '';
    if (hunk) { oldLine = Number(hunk[1]); newLine = Number(hunk[2]); kind = 'hunk'; }
    else if (header) { kind = 'file-header'; }
    else if (line.startsWith('+')) { kind = 'addition'; newNo = newLine++; }
    else if (line.startsWith('-')) { kind = 'deletion'; oldNo = oldLine++; }
    else if (!line.startsWith('\\') && (oldLine || newLine)) { oldNo = oldLine++; newNo = newLine++; }
    return <div className={`diff-line ${kind}`} key={index}><span className="line-number">{oldNo}</span><span className="line-number">{newNo}</span><code>{line || ' '}</code></div>;
  })}</div>;
}
function ActivityFeed({ events, busy }: { events: Trajectory[]; busy: boolean }) {
  return <div className="activity-feed" aria-live="polite">{!events.length ? <div className="activity-empty">{busy ? <LoaderCircle size={24} className="spin"/> : <Terminal size={24}/>}<strong>{busy ? 'The agent is getting to work…' : 'A visible trail of real work.'}</strong><p>{busy ? 'Review steps appear here as they happen.' : 'Context, tool activity, and decisions appear after you run a review.'}</p></div> : <>{events.map((event, index) => <div className="activity-event" key={index}><span className="activity-node"><Check size={12}/></span><div><span className="activity-type">{event.type.replace(/[_-]/g, ' ')}</span><p>{event.message}</p></div>{event.timestamp && <time>{new Date(event.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>}</div>)}{busy && <div className="activity-running"><LoaderCircle size={15} className="spin"/>Working…</div>}</>}</div>;
}

function FeedbackPanel({ selected, current, onSave }: { selected?: Experience; current?: Omit<Partial<Draft>, 'context'> & { context?: unknown }; onSave: (body: unknown, id?: string) => Promise<boolean> }) {
  const [decision, setDecision] = useState<Decision>('REJECT');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [issueTags, setIssueTags] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  useEffect(() => { setDecision(selected?.human_feedback?.decision || 'REJECT'); setReason(selected?.human_feedback?.reason || ''); setIssueTags(selected?.human_feedback?.issue_tags || selected?.human_feedback?.issues || []); setEditing(false); }, [selected?.id, selected?.human_feedback?.reason, current?.diff]);
  const saved = !!selected?.human_feedback && !editing;
  const isCorrection = selected?.agent_review && selected.agent_review.decision !== decision;
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!reason.trim() || !current?.diff || !current.title || (decision === 'REJECT' && !issueTags.length)) return;
    setSaving(true);
    const result = await onSave(selected ? { decision, reason: reason.trim(), issues: decision === 'REJECT' ? issueTags : [], approved: true } : { title: current.title, diff: current.diff, context: current.context || '', repo: current.repo || 'local', decision, reason: reason.trim(), issues: decision === 'REJECT' ? issueTags : [], approved: true }, selected?.id);
    if (result) setEditing(false);
    setSaving(false);
  };
  return <section className="panel feedback-panel"><div className="panel-title"><div><MessageSquare size={17}/><h2>Your judgment</h2></div><span className="human-badge">HUMAN</span></div><div className="feedback-body"><div className="feedback-heading"><span className={`feedback-symbol ${saved ? 'saved' : ''}`}>{saved ? <CheckCheck size={22}/> : <Command size={21}/>}</span><h3>{saved ? 'Experience captured.' : selected?.agent_review ? 'You make the final call.' : 'Teach it how you think.'}</h3><p>{saved ? 'This feedback is saved with the original change and review.' : selected?.agent_review ? 'Confirm the review or correct it. The reason is where the learning starts.' : 'Label this change and explain your judgment to create a training example.'}</p></div><form onSubmit={event => void submit(event)}><label className="field-label">YOUR DECISION</label><div className="decision-group"><button type="button" className={`decision-button approve ${decision === 'APPROVE' ? 'chosen' : ''}`} disabled={saved} aria-pressed={decision === 'APPROVE'} onClick={() => setDecision('APPROVE')}><Check size={16}/>Approve</button><button type="button" className={`decision-button reject ${decision === 'REJECT' ? 'chosen' : ''}`} disabled={saved} aria-pressed={decision === 'REJECT'} onClick={() => setDecision('REJECT')}><X size={16}/>Request changes</button></div>{decision === 'REJECT' && <details className="issue-selector"><summary>{issueTags.length ? `${issueTags.length} issue${issueTags.length === 1 ? '' : 's'} selected` : 'Select issues (required)'}<ChevronDown size={13}/></summary><div className="issue-options">{Object.entries(ISSUE_LABELS).map(([tag, label]) => <label key={tag}><input type="checkbox" checked={issueTags.includes(tag)} disabled={saved} onChange={event => setIssueTags(items => event.target.checked ? [...items, tag] : items.filter(item => item !== tag))}/><span>{label}</span></label>)}</div></details>}<label className="reason-label" htmlFor="feedback-reason">{saved ? 'What you taught it' : 'What should it learn?'}</label><textarea id="feedback-reason" className="feedback-textarea" value={reason} onChange={event => setReason(event.target.value)} readOnly={saved} placeholder="Be specific. Which issue matters, and what would make this change acceptable?" rows={5} required/><div className="feedback-tip"><Sparkles size={13}/><span>{isCorrection ? 'A different decision. A valuable correction.' : 'Specific feedback makes useful training data.'}</span></div>{saved ? <button type="button" className="button button-secondary button-full" onClick={() => setEditing(true)}>Edit feedback</button> : <LoadingButton type="submit" className="button button-dark button-full" busy={saving} disabled={!reason.trim() || !current?.diff || !current?.title || (decision === 'REJECT' && !issueTags.length)}>{saving ? 'Saving experience…' : selected ? 'Save feedback' : 'Save labeled experience'}{!saving && <ArrowRight size={16}/>}</LoadingButton>}</form></div><div className="feedback-bottom"><span className="small-orbit"/><span>One correction. Better judgment tomorrow.</span></div></section>;
}

function ExperienceLibrary({ experiences, eligible, onSelect, onReview, onLearn }: { experiences: Experience[]; eligible: number; onSelect: (id: string) => void; onReview: () => void; onLearn: () => void }) {
  const [filter, setFilter] = useState<'all' | 'corrected' | 'pending'>('all');
  const [search, setSearch] = useState('');
  const filtered = experiences.filter(item => (!search || `${item.title} ${item.repo} ${item.human_feedback?.reason || ''}`.toLowerCase().includes(search.toLowerCase())) && (filter === 'all' || filter === 'corrected' && !!item.human_feedback || filter === 'pending' && !item.human_feedback));
  return <div className="library-layout"><div className="panel"><div className="library-toolbar"><div className="filter-tabs" role="tablist" aria-label="Experience filter">{(['all', 'corrected', 'pending'] as const).map(item => <button key={item} role="tab" aria-selected={filter === item} className={filter === item ? 'selected' : ''} onClick={() => setFilter(item)}>{item === 'all' ? 'All experience' : item === 'corrected' ? 'With feedback' : 'Needs judgment'}</button>)}</div><input className="search-input" aria-label="Search experiences" placeholder="Search your experience…" value={search} onChange={event => setSearch(event.target.value)}/><a className="button button-secondary button-small" href="/api/dataset/export" download><ArrowDownToLine size={15}/>Export</a></div>{filtered.length ? <div className="experience-table"><div className="experience-table-head"><span>EXPERIENCE</span><span>AGENT → HUMAN</span><span>SIGNAL</span><span>SAVED</span></div>{filtered.map(item => <button key={item.id} className="experience-row" onClick={() => onSelect(item.id)}><div className="experience-title"><span className="table-icon"><GitPullRequest size={17}/></span><div><strong>{item.title}</strong><small>{item.repo || 'Local repository'}</small></div></div><div className="decision-comparison"><span className={item.agent_review?.decision === 'REJECT' ? 'text-red' : 'text-muted'}>{item.agent_review?.decision || '—'}</span><ArrowRight size={13}/><strong className={item.human_feedback?.decision === 'REJECT' ? 'text-red' : item.human_feedback ? 'text-green' : 'text-muted'}>{item.human_feedback?.decision || 'Pending'}</strong></div><div>{item.human_feedback ? <Pill tone={item.agent_review && item.agent_review.decision !== item.human_feedback.decision ? 'blue' : 'green'}>{item.agent_review ? item.agent_review.decision !== item.human_feedback.decision ? 'Correction' : 'Confirmed' : 'Human label'}</Pill> : <Pill>Unlabeled</Pill>}</div><div className="row-date">{dateText(item.created_at)}<ChevronRight size={14}/></div></button>)}</div> : <Empty icon={Layers3} title={experiences.length ? 'No matching experiences.' : 'The beginning of a better reviewer.'} description={experiences.length ? 'Try a different filter or search.' : 'Run a review or label a sample change. Every saved judgment keeps its context, so the learning remains grounded in real work.'} action={!experiences.length && <button className="button button-primary" onClick={onReview}>Create your first experience<ArrowRight size={16}/></button>}/>}</div><div className="library-bottom"><div><span className="large-inline-number">{eligible}</span><div><strong>Examples ready for learning</strong><p>Human feedback is the signal. The original change is the context.</p></div></div><button className="button button-secondary" onClick={onLearn}>Open learning studio<ArrowRight size={16}/></button></div></div>;
}

function LearningStudio({ state, riverReady, busy, activeJob, events, onConnect, onTrain, onReview, onReplay }: { state: State; riverReady: boolean; busy: boolean; activeJob: Job | null; events: Trajectory[]; onConnect: () => void; onTrain: (body: unknown) => void; onReview: () => void; onReplay: () => void }) {
  const [name, setName] = useState('reflex-engineering-v1');
  const [method, setMethod] = useState<'sft' | 'sft+rl'>('sft');
  const [copied, setCopied] = useState('');
  const [copyError, setCopyError] = useState('');
  const copyCheckpoint = async (item: Checkpoint) => { try { await navigator.clipboard.writeText(item.checkpoint || item.id); setCopied(item.id); setCopyError(''); window.setTimeout(() => setCopied(''), 2500); } catch { setCopyError('Clipboard access was blocked. Select and copy the checkpoint reference shown below.'); } };
  const trainingBusy = busy && activeJob?.type === 'training';
  return <div className="learning-layout"><section className="panel training-panel"><div className="panel-title"><div><Zap size={18}/><h2>A specialist with your judgment</h2></div><Pill tone="blue">RIVER TRAINING</Pill></div><div className="training-intro"><div className="training-graphic" aria-hidden="true"><div className="experience-stack"><span/><span/><span><Layers3 size={23}/></span></div><div className="graphic-dashes"/><div className="training-core"><Brand compact/></div><div className="graphic-dashes"/><div className="checkpoint-orb"><GitBranch size={27}/></div></div><div className="training-graphic-labels"><span>Your experience</span><span>Learned weights</span><span>Your checkpoint</span></div><h3>Let the work change the model.</h3><p>Teach the reviewer from explicit corrections, then save its trained weights as a checkpoint you can evaluate and reuse.</p></div><div className="training-form"><div className="dataset-summary"><div><Database size={20}/><span><strong>{state.stats.eligible} labeled examples</strong><small>{state.stats.eligible < 2 ? 'Confirm at least two distinct changes to start' : `From ${state.stats.experiences} saved experiences`}</small></span></div>{state.stats.eligible >= 2 ? <Pill tone="green"><Check size={12}/>Ready to train</Pill> : <button className="text-button" onClick={onReview}>Add feedback<ArrowUpRight size={13}/></button>}</div><label className="input-label">Checkpoint name<input value={name} onChange={event => setName(event.target.value)} placeholder="reflex-engineering-v1" maxLength={64} pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"/></label><label className="field-label">LEARNING METHOD</label><div className="method-options"><button className={`method-option ${method === 'sft' ? 'selected' : ''}`} onClick={() => setMethod('sft')} aria-pressed={method === 'sft'}><span className="radio-dot"/><span><strong>Learn from corrections <Pill>SFT</Pill></strong><small>Train on the review decisions you explicitly confirmed.</small></span></button>{state.status.training_methods?.includes('sft+rl') && <button className={`method-option ${method === 'sft+rl' ? 'selected' : ''}`} onClick={() => setMethod('sft+rl')} aria-pressed={method === 'sft+rl'}><span className="radio-dot"/><span><strong>Refine with reward learning <Pill>SFT + RL</Pill></strong><small>Reward correct decisions and issue tags from your confirmed examples.</small></span></button>}</div><div className="training-disclosure"><ShieldCheck size={16}/><p>Training sends the selected examples to River. Review your dataset before starting. Your held-out evaluation set stays separate.</p><a href="/api/dataset/export" download aria-label="Export the training dataset"><ArrowDownToLine size={16}/></a></div>{riverReady ? <LoadingButton className="button button-primary button-full button-large" busy={trainingBusy} disabled={busy || state.stats.eligible < 2 || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name.trim())} onClick={() => onTrain({ name: name.trim(), method })}>{trainingBusy ? 'Learning from your experience…' : <><Zap size={17}/>Turn experience into intelligence<ArrowRight size={17}/></>}</LoadingButton> : <button className="button button-primary button-full button-large" onClick={onConnect}><Unplug size={17}/>Connect River to start learning<ArrowUpRight size={17}/></button>}</div></section><aside className="learning-aside">{(trainingBusy || activeJob?.type === 'training' && events.length > 0) && <div className="panel"><div className="panel-title"><div><Radio size={17}/><h2>Training progress</h2></div>{trainingBusy && <Pill tone="blue">LIVE</Pill>}</div><ActivityFeed events={events} busy={trainingBusy}/></div>}<div className="panel checkpoint-panel"><div className="panel-title"><div><GitBranch size={18}/><h2>Your checkpoints</h2></div><span className="subtle-count">{state.checkpoints.length}</span></div>{state.checkpoints.length ? <div className="checkpoint-list">{state.checkpoints.map(item => <div className="checkpoint-item" key={item.id}><span className="checkpoint-icon"><GitBranch size={20}/></span><div><strong>{item.name}</strong><code className="checkpoint-reference" title={item.checkpoint || item.id}>{item.checkpoint || item.id}</code><span>{dateText(item.created_at)}</span>{item.metrics && <div className="checkpoint-metrics">{typeof item.metrics.sft_steps === 'number' && <span>{item.metrics.sft_steps} SFT steps</span>}{item.metrics.rl_status === 'updated' && <span>{String(item.metrics.rl_steps)} RL steps</span>}{item.metrics.rl_status === 'skipped_zero_variance' && <span className="rl-skipped">RL skipped: equal rewards</span>}</div>}<div className="checkpoint-actions"><button className="text-button" aria-label={`Copy checkpoint ${item.name}`} onClick={() => void copyCheckpoint(item)}>{copied === item.id ? <Check size={12}/> : <Copy size={12}/>}{copied === item.id ? 'Copied' : 'Copy reference'}</button>{item.dataset_hash && <a className="text-button" href={`/api/datasets/${encodeURIComponent(item.dataset_hash)}/export`} download><Database size={12}/>Training data</a>}<a className="text-button" href="https://console.river.ai/" target="_blank" rel="noreferrer"><ArrowDownToLine size={12}/>Download weights<ExternalLink size={10}/></a></div></div><CircleCheck size={16}/></div>)}{copyError && <p className="copy-error" role="alert">{copyError}</p>}<p className="checkpoint-download-note">River Console → Checkpoints → select your checkpoint → Download. Download the files to keep a local copy of your trained weights.</p><button className="button button-secondary button-full" onClick={onReplay}>Evaluate your checkpoint<ArrowRight size={15}/></button></div> : <Empty icon={GitBranch} title="A model that belongs to you." description="Your first trained checkpoint will appear here, with a durable reference to its weights."/>}</div><div className="learning-principle"><span className="quote-mark">“</span><p>Memory changes what an agent knows.<br/><strong>Learning changes what it is good at.</strong></p><div className="principle-rule"/><span>THE REFLEX PRINCIPLE</span></div></aside></div>;
}

function EvaluationLab({ evaluations, checkpoints, riverReady, busy, activeJob, events, onConnect, onEvaluate, onLearn }: { evaluations: Evaluation[]; checkpoints: Checkpoint[]; riverReady: boolean; busy: boolean; activeJob: Job | null; events: Trajectory[]; onConnect: () => void; onEvaluate: (checkpoint: string) => void; onLearn: () => void }) {
  const [checkpoint, setCheckpoint] = useState('');
  const [selectedEvaluation, setSelectedEvaluation] = useState('');
  const evaluation = evaluations.find(item => item.id === selectedEvaluation) || evaluations[0];
  const evalBusy = busy && activeJob?.type === 'evaluation';
  const chosenCheckpoint = checkpoint || checkpoints[0]?.checkpoint || checkpoints[0]?.id || '';
  return <div className="evaluation-layout"><div className="panel eval-runner"><div><span className="eval-runner-icon"><FlaskConical size={22}/></span><div><h2>One test set. Three conditions.</h2><p>Same tasks and scoring rules. Only the learning condition changes.</p></div></div><div className="eval-controls"><label className="sr-only" htmlFor="eval-checkpoint">Checkpoint to evaluate</label><select id="eval-checkpoint" value={chosenCheckpoint} onChange={event => setCheckpoint(event.target.value)}>{!checkpoints.length && <option value="">No checkpoint yet</option>}{checkpoints.map(item => <option key={item.id} value={item.checkpoint || item.id}>{item.name}</option>)}</select>{!riverReady ? <button className="button button-primary" onClick={onConnect}>Connect River<ArrowUpRight size={15}/></button> : <LoadingButton className="button button-primary" busy={evalBusy} disabled={busy || !chosenCheckpoint} onClick={() => onEvaluate(chosenCheckpoint)}>{evalBusy ? 'Evaluating…' : <><Play size={14} fill="currentColor"/>Run evaluation</>}</LoadingButton>}</div></div>
      {evalBusy && <div className="panel eval-progress"><div className="panel-title"><div><Activity size={17}/><h2>Held-out evaluation in progress</h2></div><Pill tone="blue">LIVE</Pill></div><ActivityFeed events={events} busy/></div>}
      <div className="comparison-grid">{(['base', 'memory', 'learned'] as Condition[]).map((condition, index) => { const result = evaluation?.conditions?.find(item => item.name === condition); const accuracy = result && result.total > 0 && Number.isFinite(result.accuracy) ? Math.round(result.accuracy <= 1 ? result.accuracy * 100 : result.accuracy) : null; return <div className={`comparison-card ${condition === 'learned' ? 'learned' : ''}`} key={condition}><div className="condition-heading"><span>CONDITION 0{index + 1}</span>{condition === 'learned' ? <Sparkles size={18}/> : condition === 'memory' ? <BookOpen size={18}/> : <Circle size={18}/>}</div><h3>{conditionName(condition)}</h3><p>{condition === 'base' ? 'The starting point. No saved feedback.' : condition === 'memory' ? 'Past corrections added to the context.' : 'Your checkpoint, with the same memory.'}</p><div className="score">{accuracy !== null ? <>{accuracy}<span>%</span></> : <span className="unmeasured-score">—</span>}</div><span className="score-caption">{result ? `${result.correct} of ${result.total} decisions correct${evaluation?.status !== 'completed' ? ' · partial' : ''}` : 'Awaiting measured results'}</span><div className="score-track"><span style={{ width: `${accuracy || 0}%` }}/></div><div className="condition-capabilities"><span><Check size={13}/>Fixed review instructions</span><span className={condition === 'base' ? 'inactive' : ''}>{condition === 'base' ? <X size={13}/> : <Check size={13}/>}Saved feedback in context</span><span className={condition !== 'learned' ? 'inactive' : ''}>{condition !== 'learned' ? <X size={13}/> : <Check size={13}/>}Learned model weights</span></div></div>; })}</div>
      {(evaluation?.status === 'failed' || evaluation?.status === 'interrupted') && <div className="banner banner-error" role="alert"><CircleAlert size={17}/><p>Evaluation stopped. {evaluation.error || 'Review the saved events before trying again.'} Any scores shown are partial.</p></div>}{evaluation ? <div className="panel evaluation-details"><div className="panel-title"><div><ShieldCheck size={17}/><h2>Evaluation evidence</h2></div>{evaluations.length > 1 && <select aria-label="Past evaluation" value={evaluation.id} onChange={event => setSelectedEvaluation(event.target.value)}>{evaluations.map(item => <option key={item.id} value={item.id}>{dateText(item.created_at)} · {shortId(item.id)}</option>)}</select>}<Pill tone={evaluation.status === 'completed' ? 'green' : 'amber'}>{evaluation.status === 'completed' ? 'MEASURED' : 'PARTIAL RESULTS'}</Pill></div><div className="evaluation-provenance"><span>Checkpoint <code>{shortId(evaluation.checkpoint)}</code></span>{evaluation.matched_prompts && <span className="text-green"><Check size={12}/> Memory and learned prompts matched</span>}{evaluation.prompt_hash && <span>Prompt hash <code title={evaluation.prompt_hash}>{shortId(evaluation.prompt_hash)}</code></span>}</div><div className="eval-result-list">{evaluation.conditions.flatMap(condition => (condition.results || []).map((result, index) => <div className="eval-result" key={`${condition.name}-${index}`}><span className={`eval-result-icon ${(result.correct ?? result.score?.correct_decision) ? 'correct' : 'incorrect'}`}>{(result.correct ?? result.score?.correct_decision) ? <Check size={14}/> : <X size={14}/>}</span><div><strong>{result.title || result.case_id || result.sample_id || `Held-out change ${index + 1}`}</strong><small>{result.error || `${conditionName(condition.name)} · ${result.decision || result.review?.decision || 'No decision'}${result.expected ? ` · expected ${result.expected}` : ''}`}</small></div><Pill tone={(result.correct ?? result.score?.correct_decision) ? 'green' : 'red'}>{(result.correct ?? result.score?.correct_decision) ? 'Correct' : result.error ? 'Error' : 'Missed'}</Pill></div>))}</div></div> : <div className="panel eval-empty"><div className="eval-empty-copy"><div className="empty-icon"><ShieldCheck size={23}/></div><div><h3>Improvement is a result to earn.</h3><p>Nothing here is prefilled. Train a checkpoint and run the held-out suite to see what your specialist actually learned.</p></div></div>{!checkpoints.length && <button className="button button-secondary" onClick={onLearn}>Create a checkpoint<ArrowRight size={16}/></button>}</div>}
      <div className="evaluation-note"><CircleAlert size={15}/><p>This benchmark uses fictional, held-out PRs. Memory and learned conditions receive identical inputs; the base condition omits prior feedback. Results describe this small suite, not general performance on your repository.</p></div>
    </div>;
}

function Connections({ riverReady, riverVerified, ufoReady, model, onClose, onRefresh }: { riverReady: boolean; riverVerified: boolean; ufoReady: boolean; model?: string; onClose: () => void; onRefresh: () => Promise<unknown> }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const nodes = dialogRef.current?.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex="0"]');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', keydown);
    const oldOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', keydown); document.body.style.overflow = oldOverflow; previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}><div className="connections-modal" role="dialog" aria-modal="true" aria-labelledby="connections-title" ref={dialogRef}><div className="modal-heading"><div><span className="eyebrow">THE LEARNING LOOP</span><h2 id="connections-title">Connect your intelligence.</h2></div><button ref={closeRef} className="icon-button" aria-label="Close connections" onClick={onClose}><X size={20}/></button></div><p className="modal-description">Reflex keeps your experience locally. Connect the services that run the work and train the specialist.</p><section className="connection-card"><div className="connection-card-heading"><span className="service-icon river-icon"><Activity size={23}/></span><div><h3>River</h3><p>The learning layer</p></div><Pill tone={riverReady ? 'green' : 'amber'}><StatusDot ready={riverReady}/>{riverVerified ? 'Verified' : riverReady ? 'Key detected' : 'Needs setup'}</Pill></div>{riverReady ? <p className="connection-ready">{riverVerified ? 'A River operation has completed successfully' : 'Your key is detected; run a review to verify access'}{model ? <> with <code>{model}</code></> : ''}.</p> : <><p>Add your River API key to the backend environment, then restart the server. Your key stays on the server.</p><div className="env-code"><code>RIVER_API_KEY=your-river-api-key</code></div><p className="connection-help">Use the <code>.env.example</code> file in the project for the complete setup.</p></>}</section><section className="connection-card"><div className="connection-card-heading"><span className="service-icon ufo-icon"><Terminal size={21}/></span><div><h3>UFO</h3><p>The experience layer</p></div><Pill tone={ufoReady ? 'green' : 'neutral'}><StatusDot ready={ufoReady}/>{ufoReady ? 'Experience received' : 'Tool integration'}</Pill></div><p>Install the Reflex extension in your self-hosted UFO workspace. Review results, tool activity, and human corrections form a reusable experience.</p><div className="env-code"><code>review_code_with_reflex(diff)</code></div><p className="connection-help">See the repository setup guide for the UFO tool and trajectory import. Hosted UFO connectivity has not been verified.</p></section><div className="modal-footer"><span><ShieldCheck size={15}/>Credentials never enter the browser.</span><LoadingButton className="button button-primary" busy={refreshing} onClick={async () => { setRefreshing(true); await onRefresh(); setRefreshing(false); }}>{!refreshing && <RotateCcw size={15}/>}Check connection</LoadingButton></div></div></div>;
}
