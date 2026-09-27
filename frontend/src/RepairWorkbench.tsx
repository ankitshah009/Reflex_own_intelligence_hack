import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronDown,
  ChevronRight, CircleAlert, CircleCheck, Code2, Copy, Database, ExternalLink, FileCode2,
  FlaskConical, GitBranch, GitCompareArrows, GitPullRequest, Layers3, LoaderCircle, Menu,
  Package, Play, Plus, RotateCcw, Settings2, ShoppingBag, Sparkles, Terminal,
  Unplug, X, Zap,
} from 'lucide-react';
import { api, post } from './api';
import { EMPTY_REPAIR_STATE } from './repairTypes';
import RepositoryWorkbench from './RepositoryWorkbench';
import type { JsonObject, Repair, RepairAction, RepairCase, RepairCheckpoint, RepairEvaluation, RepairEvent, RepairJob, RepairReport, RepairState } from './repairTypes';

type View = 'workbench' | 'learning' | 'repository';
type DetailTab = 'source' | 'diff' | 'checks' | 'responses';
type Condition = 'base' | 'memory' | 'learned';
const TERMINAL = new Set(['completed', 'complete', 'failed', 'error', 'interrupted', 'cancelled']);
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error);
const humanize = (value: string) => value.replace(/[_-]/g, ' ').replace(/^./, char => char.toUpperCase());
const stringify = (value: unknown) => JSON.stringify(value, null, 2);
const passedCount = (report?: RepairReport | null) => report ? typeof report.passed === 'number' ? report.passed : report.checks.filter(check => check.passed).length : 0;
const didPass = (report?: RepairReport | null) => !!report && report.total > 0 && passedCount(report) === report.total;
const asRecord = (value: unknown): JsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {};
const shorten = (value: string, length = 25) => value.length > length ? `${value.slice(0, length - 7)}…${value.slice(-6)}` : value;
const time = (value?: string) => value ? new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '';

function ReflexMark() {
  return <svg className="rx-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M6 27V7l8-4v20l-8 4Z" fill="currentColor"/><path d="m17 4 9-3v14l-9 4V4ZM17 23l9-4v10l-9-4v-2Z" fill="currentColor"/></svg>;
}
function Button({ busy, children, className = '', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return <button {...props} className={`rx-button ${className}`} disabled={props.disabled || busy}>{busy && <LoaderCircle size={15} className="rx-spin"/>}{children}</button>;
}
function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'blue' | 'green' | 'red' }) {
  return <span className={`rx-tag rx-tag-${tone}`}>{children}</span>;
}
function Status({ report }: { report?: RepairReport | null }) {
  if (!report) return <Tag>Not run</Tag>;
  return <Tag tone={didPass(report) ? 'green' : 'red'}>{didPass(report) ? <Check size={12}/> : <CircleAlert size={12}/>} {passedCount(report)}/{report.total} checks pass</Tag>;
}
function Modal({ title, subtitle, onClose, children, wide = false }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const close = ref.current?.querySelector<HTMLButtonElement>('button');
    close?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key !== 'Tab') return;
      const nodes = ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, textarea, select, summary');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', key); document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  return <div className="rx-modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><div className={`rx-modal ${wide ? 'rx-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="rx-modal-title" ref={ref}><div className="rx-modal-header"><div><h2 id="rx-modal-title">{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="rx-icon-button" onClick={onClose} aria-label="Close dialog"><X size={20}/></button></div>{children}</div></div>;
}

export default function RepairWorkbench({ onLegacy }: { onLegacy: () => void }) {
  const [state, setState] = useState<RepairState>(EMPTY_REPAIR_STATE);
  const [view, setView] = useState<View>('workbench');
  const [caseId, setCaseId] = useState('');
  const [source, setSource] = useState('');
  const [selectedRepairId, setSelectedRepairId] = useState('');
  const [report, setReport] = useState<RepairReport | null>(null);
  const [replayEvents, setReplayEvents] = useState<JsonObject[]>([]);
  const [previewVersion, setPreviewVersion] = useState<'original' | 'working'>('original');
  const [detailTab, setDetailTab] = useState<DetailTab>('checks');
  const [condition, setCondition] = useState<Condition>('base');
  const [checkpoint, setCheckpoint] = useState('');
  const [job, setJob] = useState<RepairJob | null>(null);
  const [events, setEvents] = useState<RepairEvent[]>([]);
  const [pending, setPending] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [toast, setToast] = useState('');
  const [connectOpen, setConnectOpen] = useState(false);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [casesOpen, setCasesOpen] = useState(false);
  const jobKind = useRef('');
  const selectedCaseRef = useRef(caseId);
  selectedCaseRef.current = caseId;
  const sourceRef = useRef(source);
  const previewVersionRef = useRef(previewVersion);
  sourceRef.current = source;
  previewVersionRef.current = previewVersion;
  const currentCase = state.cases.find(item => item.id === caseId);
  const selectedRepair = state.repairs.find(item => item.id === selectedRepairId);
  const caseRepairs = state.repairs.filter(item => item.case_id === caseId);
  const busy = !!pending || !!job && !TERMINAL.has(job.status);
  const jobBusy = !!job && !TERMINAL.has(job.status);
  const currentCaseJob = !!job && job.payload?.case_id === caseId;
  const currentCaseWorking = jobBusy && currentCaseJob;
  const backgroundLearning = jobBusy && /train|eval/.test(job?.kind || jobKind.current);
  const localBusy = !!pending || jobBusy && !backgroundLearning;
  const otherRunningCase = jobBusy && job.payload?.case_id && !currentCaseJob ? state.cases.find(item => item.id === job.payload?.case_id) : undefined;
  const previewState = report?.preview?.state || currentCase?.initial_state || {};
  const activeCheckpoint = checkpoint || state.checkpoints[0]?.id || '';
  const selectCase = (item: RepairCase) => {
    setCaseId(item.id); setSource(item.source); setSelectedRepairId(''); setReport(null);
    setReplayEvents([]); setPreviewVersion('original'); setDetailTab('checks');
    setError(''); setView('workbench'); setCasesOpen(false);
  };
  const selectRepair = (repair: Repair) => {
    setCaseId(repair.case_id); setSource(repair.human_feedback?.code || repair.code);
    setSelectedRepairId(repair.id); setReport(repair.report); setPreviewVersion('working');
    setReplayEvents([]); setDetailTab('checks'); setView('workbench');
  };
  const refresh = useCallback(async () => {
    try {
      const next = await api<RepairState>('/repairs/state');
      setState({ ...EMPTY_REPAIR_STATE, ...next, provider: { ...EMPTY_REPAIR_STATE.provider, ...next.provider }, stats: { ...EMPTY_REPAIR_STATE.stats, ...next.stats } });
      setConnectionError(''); setLoaded(true); return next;
    } catch (err) { setConnectionError(messageOf(err)); setLoaded(true); return null; }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => { if (!caseId && state.cases[0]) selectCase(state.cases[0]); }, [state.cases, caseId]);
  useEffect(() => {
    if (job && !TERMINAL.has(job.status)) return;
    const running = state.jobs.find(item => !TERMINAL.has(item.status) && (!item.kind || /repair/.test(item.kind)));
    if (running) { jobKind.current = running.kind || 'repair'; setJob(running); setEvents(running.events || []); }
  }, [state.jobs, job]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 4200); return () => window.clearTimeout(timer); }, [toast]);
  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    let cancelled = false, polling = false;
    const stream = new EventSource(`/api/jobs/${encodeURIComponent(job.id)}/events`);
    stream.onmessage = event => { try { const item = JSON.parse(event.data) as RepairEvent; setEvents(items => [...items, item].slice(-100)); } catch { /* Job polling remains authoritative. */ } };
    const poll = async () => {
      if (cancelled || polling) return;
      polling = true;
      try {
        const next = await api<RepairJob>(`/jobs/${encodeURIComponent(job.id)}`);
        if (cancelled) return;
        setJob(next);
        if (next.events?.length) setEvents(next.events);
        if (TERMINAL.has(next.status)) {
          stream.close();
          const fresh = await refresh();
          if (next.status !== 'completed' && next.status !== 'complete') setError(next.error || 'The run stopped. Inspect its execution log before trying again.');
          else {
            const result = asRecord(next.result);
            const candidate = (result.repair || result) as Repair;
            const repair = candidate.code && candidate.report ? candidate : fresh?.repairs.find(item => item.id === result.repair_id);
            if (repair && repair.case_id === selectedCaseRef.current) {
              setSelectedRepairId(repair.id); setSource(repair.code); setReport(repair.report);
              setPreviewVersion('working'); setDetailTab('checks'); setReplayEvents([]);
              setToast(didPass(repair.report) ? 'Repair verified. Review the patch and accept it.' : 'Verification finished. The failing checks show what still needs fixing.');
            } else if (jobKind.current.includes('curriculum')) setToast('Example generation finished. Saved outcomes are ready to inspect.');
            else if (jobKind.current.includes('train')) setToast('Training completed. Your repair specialist is ready to evaluate.');
            else if (jobKind.current.includes('eval')) setToast('Evaluation finished. The measured results are ready.');
          }
        }
      } catch (err) { if (!cancelled) setError(messageOf(err)); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1300);
    return () => { cancelled = true; stream.close(); window.clearInterval(timer); };
  }, [job?.id, !!job && TERMINAL.has(job.status), refresh]);

  const startJob = async (path: string, body: unknown, kind: string) => {
    if (busy) return;
    setPending(kind); setError(''); setEvents([]); jobKind.current = kind;
    try { const result = await post<{ job_id: string }>(path, body); setJob({ id: result.job_id, kind, status: 'queued', payload: asRecord(body) }); }
    catch (err) { setError(messageOf(err)); }
    finally { setPending(''); }
  };
  const reproduce = async (nextEvents?: JsonObject[], version = previewVersion, intent = 'reproduce') => {
    if (!currentCase || localBusy) return;
    const requestCaseId = currentCase.id;
    const requestSource = source;
    const eventsToRun = nextEvents ?? currentCase.reproduction;
    setPending(intent); setError('');
    try {
      const next = await post<RepairReport>('/repairs/reproduce', { case_id: requestCaseId, ...(version === 'working' ? { code: requestSource } : {}), events: eventsToRun });
      if (selectedCaseRef.current !== requestCaseId || previewVersionRef.current !== version || version === 'working' && sourceRef.current !== requestSource) return;
      setReport(next); setReplayEvents(eventsToRun); setDetailTab('checks');
      if (intent === 'verify_local') setToast(`Local verification: ${passedCount(next)}/${next.total} checks pass. Save the repair after the learning run finishes.`);
    } catch (err) { setError(messageOf(err)); }
    finally { setPending(''); }
  };
  const resetPreview = () => { setReport(null); setReplayEvents([]); setError(''); };
  const editSource = (value: string) => { setSource(value); setReport(null); setReplayEvents([]); setSelectedRepairId(''); setPreviewVersion('working'); if (!jobBusy) setEvents([]); };
  const runAgent = () => {
    if (!currentCase) return;
    if (!state.provider.configured) { setConnectOpen(true); return; }
    void startJob('/repairs/run', { case_id: caseId, condition, ...(condition === 'learned' ? { checkpoint: activeCheckpoint } : {}) }, 'repair');
  };
  const verify = () => {
    if (!currentCase || localBusy) return;
    if (backgroundLearning) {
      setPreviewVersion('working'); previewVersionRef.current = 'working';
      void reproduce(undefined, 'working', 'verify_local');
    } else void startJob('/repairs/run', { case_id: caseId, condition: 'base', code: source }, 'repair_manual');
  };
  const accept = async (reason: string) => {
    if (!selectedRepair || busy) return;
    setPending('accept'); setError('');
    try {
      const saved = await post<Repair>('/repairs/feedback', { repair_id: selectedRepair.id, code: source, reason, approved: true });
      await refresh(); setSelectedRepairId(saved.id); setToast('Repair accepted. This is now a confirmed learning example.'); return true;
    } catch (err) { setError(messageOf(err)); return false; }
    finally { setPending(''); }
  };

  return <div className="repair-app">
    <a className="rx-skip-link" href="#repair-main" onClick={() => requestAnimationFrame(() => document.getElementById('repair-main')?.focus())}>Skip to workbench</a>
    <header className="rx-topbar"><div className="rx-topbar-brand"><button className="rx-icon-button rx-mobile-menu" aria-label="Open repair cases" aria-expanded={casesOpen} onClick={() => { if (view === 'repository') setView('workbench'); setCasesOpen(!casesOpen); }}><Menu size={20}/></button><div className="rx-logo"><ReflexMark/><span>reflex<span>.</span></span></div><span className="rx-topbar-separator"/><span className="rx-workspace-name">Release workshop<ChevronDown size={13}/></span></div><nav className="rx-top-nav" aria-label="Workspace views"><button aria-current={view === 'workbench' ? 'page' : undefined} className={view === 'workbench' ? 'active' : ''} onClick={() => setView('workbench')}><Code2 size={16}/>Workbench</button><button aria-current={view === 'repository' ? 'page' : undefined} className={view === 'repository' ? 'active' : ''} onClick={() => { setCasesOpen(false); setView('repository'); }}><FileCode2 size={16}/>Repository</button><button aria-current={view === 'learning' ? 'page' : undefined} className={view === 'learning' ? 'active' : ''} onClick={() => setView('learning')}><GitBranch size={16}/>Learning & replay{(state.stats.eligible ?? state.stats.accepted) > 0 && <span>{state.stats.eligible ?? state.stats.accepted}</span>}</button></nav><div className="rx-topbar-actions"><button className={`rx-provider-button ${state.provider.verified ? 'verified' : ''}`} onClick={() => setConnectOpen(true)}><span/>{state.provider.verified ? 'River connected' : state.provider.configured ? 'River key detected' : 'Connect River'}<Settings2 size={14}/></button><div className="rx-user-avatar" title="Your local workspace">Y</div></div></header>
    <div className={`rx-shell ${view === 'repository' ? 'rx-shell-repository' : ''}`}>
      <aside className={`rx-case-rail ${casesOpen ? 'is-open' : ''}`} aria-label="Repair cases"><div className="rx-case-rail-top"><div><h2>Release checks</h2><span>{state.cases.length}</span></div><button className="rx-icon-button" title="New repair" aria-label="New repair case" onClick={() => setNewCaseOpen(true)}><Plus size={18}/></button></div><p className="rx-rail-description">Reproduce. Repair. Remember.</p><div className="rx-case-list">{state.cases.map(item => {
        const accepted = state.repairs.some(repair => repair.case_id === item.id && repair.human_feedback?.approved);
        const machineVerified = state.repairs.some(repair => repair.case_id === item.id && repair.machine_feedback?.approved);
        return <button className={`rx-case-item ${item.id === caseId && view === 'workbench' ? 'selected' : ''}`} key={item.id} onClick={() => selectCase(item)}><span className="rx-case-icon">{accepted || machineVerified ? <CheckCheck size={17}/> : /inventory|stock/i.test(item.service) ? <Package size={17}/> : /refund/i.test(item.service) ? <RotateCcw size={17}/> : <ShoppingBag size={17}/>}</span><span><strong>{item.title}</strong><small>{item.service || 'Custom handler'}{accepted ? <span>Human approved</span> : machineVerified ? <span>Machine verified</span> : item.source_kind === 'generated' ? <span>Generated</span> : null}</small></span>{item.id === caseId && view === 'workbench' && <span className="rx-case-active"/>}</button>;
      })}{loaded && !state.cases.length && <div className="rx-rail-empty"><FileCode2 size={22}/><p>No repair cases yet.</p><button onClick={() => setNewCaseOpen(true)}>Add a handler<Plus size={13}/></button></div>}</div><button className="rx-new-case" onClick={() => setNewCaseOpen(true)}><Plus size={15}/>Bring your own handler</button><div className="rx-rail-bottom"><div className="rx-experience-note"><Layers3 size={18}/><div><strong>{state.stats.accepted} human approved</strong><p>{state.stats.machine_verified ?? 0} machine verified · saved locally</p></div></div><button onClick={onLegacy} className="rx-legacy-link"><GitPullRequest size={15}/>PR review workspace<ArrowUpRight size={13}/></button><span className="rx-storage-label"><Database size={12}/>Saved on this device</span></div></aside>
      {casesOpen && <button className="rx-mobile-scrim" aria-label="Close repair cases" onClick={() => setCasesOpen(false)}/>}
      <main id="repair-main" className="rx-main" tabIndex={-1}>
        {connectionError && <div className="rx-alert" role="alert"><CircleAlert size={17}/><div><strong>Workspace unavailable</strong><p>{connectionError}</p></div><button onClick={() => void refresh()}>Retry<RotateCcw size={13}/></button></div>}
        {error && <div className="rx-alert" role="alert"><CircleAlert size={17}/><p>{error}</p><button className="rx-icon-button" aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {!loaded ? <div className="rx-loading"><LoaderCircle size={23} className="rx-spin"/><span>Opening the workshop…</span></div> : view === 'repository' ? <RepositoryWorkbench busy={busy} job={job} events={events} provider={state.provider} onConnect={() => setConnectOpen(true)} onRun={body => void startJob('/repository/run', body, 'repository_repair')} onResumeJob={next => { jobKind.current = next.kind || 'repository_repair'; setEvents(next.events || []); setJob(next); }}/> : view === 'learning' ? <LearningPanel state={state} busy={busy} job={job} events={events} onConnect={() => setConnectOpen(true)} onTrain={name => void startJob('/repairs/train', { name }, 'repair_train')} onGenerate={(count, concurrency) => void startJob('/curriculum/generate', { count, concurrency, seed: 42 }, 'repair_curriculum')} onEvaluate={value => void startJob('/repairs/evaluate', { checkpoint: value }, 'repair_evaluate')} onSelect={selectRepair} onBack={() => setView('workbench')}/> : currentCase ? <>
          {otherRunningCase && <div className="rx-background-job"><LoaderCircle size={14} className="rx-spin"/><span>Repair running: {otherRunningCase.title}</span><button onClick={() => selectCase(otherRunningCase)}>View run<ArrowRight size={13}/></button></div>}<div className="rx-workbench-header"><div className="rx-heading-content"><div className="rx-case-path"><span>{currentCase.service}</span><ChevronRight size={12}/><span>{currentCase.filename || 'handler.py'}</span>{currentCase.source_kind !== 'manual' && <span className="rx-sample-note">{currentCase.source_kind === 'generated' ? 'Generated sample' : 'Sample app'}</span>}</div><h1>{currentCase.title}</h1><p>{currentCase.description}</p></div><div className="rx-header-controls"><Button className="rx-button-secondary" busy={pending === 'reproduce'} disabled={localBusy} onClick={() => void reproduce()}><RotateCcw size={15}/>Reproduce issue</Button><Button className="rx-button-primary" busy={currentCaseWorking || pending === 'repair'} disabled={busy || condition === 'learned' && !activeCheckpoint} onClick={runAgent}><Sparkles size={15}/>{currentCaseWorking ? 'Repairing…' : 'Ask agent to repair'}</Button></div></div>
          <div className="rx-live-grid"><section className="rx-preview-panel"><div className="rx-surface-heading"><div><span className="rx-live-indicator"/><h2>App preview</h2></div><div className="rx-preview-version" aria-label="Preview source"><button className={previewVersion === 'original' ? 'active' : ''} onClick={() => { setPreviewVersion('original'); resetPreview(); }} disabled={localBusy}>Original</button><button className={previewVersion === 'working' ? 'active' : ''} onClick={() => { setPreviewVersion('working'); resetPreview(); }} disabled={localBusy || !source}>Working patch</button></div><button className="rx-icon-button" onClick={resetPreview} disabled={localBusy} title="Reset preview" aria-label="Reset preview"><RotateCcw size={14}/></button></div>
            {currentCase.source_kind === 'sample' ? <Storefront currentCase={currentCase} state={previewState} report={report} eventCount={replayEvents.length} pending={pending === 'reproduce'} busy={localBusy} onAction={action => void reproduce([...replayEvents, action.payload])}/> : <CustomPreview currentCase={currentCase} state={previewState} report={report} busy={localBusy} onReproduce={() => void reproduce()}/>}
            <div className="rx-preview-foot"><div><span className={`rx-preview-status-dot ${report ? didPass(report) ? 'pass' : 'fail' : ''}`}/>{report ? `${replayEvents.length || 'Verification'} ${replayEvents.length ? replayEvents.length === 1 ? 'event executed' : 'events executed' : 'run completed'}` : 'Initial state. Interact with the app to run the handler.'}</div>{report?.duration_ms !== undefined && <span>{Math.round(report.duration_ms)} ms</span>}</div>
          </section><AgentPanel provider={state.provider} busy={currentCaseWorking} events={currentCaseJob ? events : []} repair={selectedRepair} condition={condition} setCondition={setCondition} checkpoint={activeCheckpoint} setCheckpoint={setCheckpoint} checkpoints={state.checkpoints} onConnect={() => setConnectOpen(true)} caseRepairs={caseRepairs} onSelect={selectRepair} />
          </div>
          <section className="rx-code-panel"><div className="rx-code-toolbar"><div className="rx-detail-tabs" role="tablist" aria-label="Repair details"><button role="tab" aria-selected={detailTab === 'checks'} className={detailTab === 'checks' ? 'active' : ''} onClick={() => setDetailTab('checks')}><CircleCheck size={15}/>Verification{report && <span className={didPass(report) ? 'pass' : 'fail'}>{passedCount(report)}/{report.total}</span>}</button><button role="tab" aria-selected={detailTab === 'source'} className={detailTab === 'source' ? 'active' : ''} onClick={() => setDetailTab('source')}><FileCode2 size={15}/>Handler code</button><button role="tab" aria-selected={detailTab === 'diff'} className={detailTab === 'diff' ? 'active' : ''} onClick={() => setDetailTab('diff')}><GitCompareArrows size={15}/>Patch</button><button role="tab" aria-selected={detailTab === 'responses'} className={detailTab === 'responses' ? 'active' : ''} onClick={() => setDetailTab('responses')}><Terminal size={15}/>Responses</button></div><div className="rx-code-actions"><span>{currentCase.filename || 'handler.py'}</span><Button busy={pending === 'repair_manual' || pending === 'verify_local'} className="rx-button-secondary rx-button-small" disabled={localBusy || !source.trim()} onClick={verify}><Play size={12} fill="currentColor"/>Verify patch</Button></div></div>
            <div className="rx-detail-content" role="tabpanel">
              {detailTab === 'checks' && <Verification report={report} expected={currentCase.expected_behavior} onEdit={() => setDetailTab('source')} onReproduce={() => void reproduce()} busy={localBusy}/>}
              {detailTab === 'source' && <CodeEditor value={source} onChange={editSource} filename={currentCase.filename || 'handler.py'} changed={source !== currentCase.source} onReset={() => { editSource(currentCase.source); setPreviewVersion('original'); }}/>}
              {detailTab === 'diff' && <PatchView diff={selectedRepair?.diff} stale={!!selectedRepair && selectedRepair.code !== source} onVerify={verify} busy={localBusy}/>}
              {detailTab === 'responses' && <div className="rx-responses"><div><h3>Executed event results</h3><p>{report ? 'Returned by the handler during the latest execution.' : 'Run a customer action or reproduce the issue to inspect the actual responses.'}</p></div><pre>{report ? stringify(report.preview.results) : 'No events executed.'}</pre></div>}
            </div>
            <AcceptRepair repair={selectedRepair} source={source} busy={busy} verifyBusy={localBusy} onAccept={accept} onVerify={verify}/>
          </section>
          <div className="rx-workbench-foot"><span><CheckCheck size={14}/>Accepted repairs become examples. Training starts only when you choose.</span><button onClick={() => setView('learning')}>Open learning & replay<ArrowRight size={14}/></button></div>
        </> : <div className="rx-no-cases"><div className="rx-empty-emblem"><Code2 size={30}/></div><h1>Bring one real failure.</h1><p>Add a Python event handler, the events that break it, and the state it should produce.</p><Button className="rx-button-primary" onClick={() => setNewCaseOpen(true)}><Plus size={16}/>Create a repair case</Button></div>}
      </main>
    </div>
    {connectOpen && <Modal title="Connect the repair specialist" subtitle="River generates patches and learns from repairs you accept." onClose={() => setConnectOpen(false)}><div className="rx-connect-body"><div className="rx-connect-status"><span className="rx-service-mark"><Zap size={25}/></span><div><strong>River</strong><p>{state.provider.verified ? 'A real River operation has completed.' : state.provider.configured ? 'API key detected. Run a repair to verify access.' : 'No API key configured yet.'}</p></div><Tag tone={state.provider.verified ? 'green' : 'neutral'}>{state.provider.verified ? 'Verified' : state.provider.configured ? 'Key detected' : 'Needs setup'}</Tag></div><p>Add your River key to this project’s <code>.env</code> file and restart the backend.</p><pre>RIVER_API_KEY=your-river-api-key</pre><div className="rx-connection-help"><Code2 size={18}/><p>You can reproduce issues, edit handlers, and verify manual repairs locally without a model connection.</p></div><Button className="rx-button-primary" onClick={() => void refresh()}><RotateCcw size={15}/>Check connection</Button></div></Modal>}
    {newCaseOpen && <NewCaseModal onClose={() => setNewCaseOpen(false)} onCreate={async body => { const created = await post<RepairCase>('/repairs/cases', body); await refresh(); selectCase(created); setNewCaseOpen(false); setToast('Repair case created. Reproduce it to see the failure.'); }}/>} 
    {toast && <div className="rx-toast" role="status"><CircleCheck size={17}/><span>{toast}</span><button className="rx-icon-button" aria-label="Dismiss notification" onClick={() => setToast('')}><X size={15}/></button></div>}
  </div>;
}

function LampIllustration() {
  return <svg className="rx-lamp-art" viewBox="0 0 430 390" role="img" aria-label="A cobalt blue desk lamp on a soft grey studio background"><defs><linearGradient id="lamp-shade" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#6891e3"/><stop offset=".38" stopColor="#3867bb"/><stop offset="1" stopColor="#24477f"/></linearGradient><linearGradient id="lamp-stem" x1="0" x2="1"><stop stopColor="#194478"/><stop offset=".43" stopColor="#5483c9"/><stop offset="1" stopColor="#284d83"/></linearGradient><linearGradient id="lamp-base" x1="0" y1="0" x2="1" y2=".8"><stop stopColor="#5785ce"/><stop offset="1" stopColor="#1d447b"/></linearGradient><radialGradient id="lamp-glow"><stop stopColor="#f7f0d9" stopOpacity=".8"/><stop offset="1" stopColor="#f7f0d9" stopOpacity="0"/></radialGradient><filter id="lamp-shadow" x="-50%" y="-100%" width="200%" height="300%"><feGaussianBlur stdDeviation="12"/></filter><linearGradient id="lamp-inner" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#f5e8c8"/><stop offset="1" stopColor="#fdf7e7"/></linearGradient></defs><ellipse cx="211" cy="328" rx="130" ry="18" fill="#677487" opacity=".18" filter="url(#lamp-shadow)"/><ellipse cx="255" cy="297" rx="112" ry="51" fill="url(#lamp-glow)"/><path d="M232 315c24 4 45 5 62 16s23 13 58 10" fill="none" stroke="#65707a" strokeWidth="3" strokeLinecap="round"/><path d="M157 306c0-16 116-18 116 0v10c0 19-116 19-116 0v-10Z" fill="#1c416f"/><ellipse cx="215" cy="304" rx="58" ry="17" fill="url(#lamp-base)"/><ellipse cx="215" cy="300" rx="39" ry="9" fill="#4475bd" opacity=".6"/><path d="M207 296V154c0-11 5-20 15-26" stroke="url(#lamp-stem)" strokeWidth="14" fill="none"/><path d="M209 287V157c0-8 5-17 10-21" stroke="#78a0de" strokeWidth="2" fill="none" opacity=".55"/><circle cx="219" cy="132" r="11" fill="#1d477a"/><circle cx="219" cy="132" r="6" fill="#6691d4"/><g transform="rotate(23 224 124)"><path d="M168 122c4-28 25-48 52-48 28 0 51 18 58 47l13 25H154l14-24Z" fill="url(#lamp-shade)"/><ellipse cx="222.5" cy="145" rx="68.5" ry="18" fill="#1b3e6d"/><ellipse cx="222.5" cy="145" rx="61" ry="13" fill="url(#lamp-inner)"/><ellipse cx="222" cy="145" rx="14" ry="7" fill="#fffdfa"/><path d="M183 110c8-17 23-27 40-28" fill="none" stroke="#a8c5f2" strokeWidth="2" strokeLinecap="round" opacity=".55"/></g><circle cx="238" cy="298" r="3" fill="#173d6d"/><path d="M169 309c19 10 69 14 92 1" fill="none" stroke="#7a9bca" strokeWidth="1" opacity=".5"/></svg>;
}

function Storefront({ currentCase, state, report, eventCount, pending, busy, onAction }: { currentCase: RepairCase; state: JsonObject; report: RepairReport | null; eventCount: number; pending: boolean; busy: boolean; onAction: (action: RepairAction) => void }) {
  const inventory = asRecord(state.inventory);
  const inventoryEntries = Object.entries(inventory);
  const orders = Array.isArray(state.orders) ? state.orders : [];
  const refunds = Array.isArray(state.refunds) ? state.refunds : [];
  const isRefund = /refund/i.test(currentCase.service);
  const isInventory = /inventory|stock/i.test(currentCase.service);
  const primary = currentCase.actions?.[0];
  const secondary = currentCase.actions?.slice(1) || [];
  const payload = primary?.payload || {};
  const activeSku = typeof payload.sku === 'string' ? payload.sku : inventoryEntries[0]?.[0];
  const stockValue = activeSku ? inventory[activeSku] : null;
  const stock = typeof stockValue === 'number' ? stockValue : typeof state.stock === 'number' ? state.stock : null;
  const quantity = typeof payload.quantity === 'number' ? payload.quantity : 1;
  const amount = typeof payload.total_cents === 'number' ? payload.total_cents / 100 : null;
  const records = isRefund ? refunds : orders;
  return <div className="rx-storefront">
    <div className="rx-store-header"><a href="#storefront" onClick={event => event.preventDefault()} aria-label="Northline Supply example storefront"><span className="rx-store-logomark">n<span/></span>northline<span className="rx-store-supply">supply</span></a><div><span>Thoughtful things. Everyday.</span><span className="rx-store-bag"><ShoppingBag size={16}/><span>{orders.length}</span></span></div></div>
    <div className="rx-store-product"><div className="rx-product-art"><span className="rx-art-note">The desk collection</span><LampIllustration/><div className="rx-art-swatches" aria-label="Product color cobalt"><span className="selected"/><span/><span/></div><span className="rx-product-index">Designed for your everyday.</span></div><div className="rx-product-detail"><span className="rx-store-category">Light, considered.</span><h2>The everyday<br/>desk lamp.</h2><p className="rx-product-description">A little focus for your corner of the world. Soft light. A considered silhouette.</p><div className="rx-product-color"><span/>Cobalt blue{activeSku && <small>SKU {activeSku}</small>}</div><div className="rx-stock-line"><span className={stock !== null && stock > 0 ? 'in-stock' : ''}/>{stock === null ? 'Inventory shown below' : `${stock} in stock`}</div><div className="rx-order-summary"><span>{isInventory ? 'Inventory event' : isRefund ? 'Refund event' : `Quantity ${quantity}`}</span><strong>{amount !== null ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount) : 'Live handler'}</strong></div><Button className="rx-store-checkout" busy={pending} disabled={busy || !primary} onClick={() => primary && onAction(primary)}>{isInventory ? <Package size={15}/> : isRefund ? <RotateCcw size={15}/> : <ShoppingBag size={15}/>}{primary ? isInventory ? 'Apply stock update' : isRefund ? 'Issue refund' : /orders/i.test(currentCase.service) ? 'Cancel order' : 'Place order' : 'No action available'}{!pending && <ArrowRight size={15}/>}</Button>{secondary.map(action => <button key={action.id} className="rx-store-secondary" disabled={busy} onClick={() => onAction(action)}><RotateCcw size={13}/>{action.label}</button>)}<p className="rx-store-test-note">{eventCount > 0 ? 'Click again to replay the same request.' : 'Try a customer action, then repeat it.'}</p></div></div>
    <div className="rx-store-ledger"><div className="rx-ledger-heading"><span>{isRefund ? 'Refund activity' : 'Order activity'}</span><span>{report ? 'Handler output' : 'Initial state'}</span></div>{records.length ? <div className="rx-order-rows">{records.slice(-3).map((raw, index) => { const order = asRecord(raw); const id = String(order.order_id || order.id || order.refund_id || `Record ${index + 1}`); return <div className="rx-order-row" key={`${id}-${index}`}><span className="rx-order-icon">{isRefund ? <RotateCcw size={13}/> : <Package size={13}/>}</span><div><strong>{id}</strong><span>{String(order.sku || 'Customer request')}{order.quantity != null ? ` · ${String(order.quantity)} items` : ''}</span></div><span>{order.status ? humanize(String(order.status)) : 'Recorded'}</span></div>; })}</div> : <div className="rx-no-orders"><ShoppingBag size={15}/><span>{isRefund ? 'No refunds recorded.' : 'Your first order will appear here.'}</span></div>}<div className="rx-ledger-bottom"><span><strong>{orders.length}</strong> {orders.length === 1 ? 'order' : 'orders'} recorded</span><span>{stock !== null ? <><strong>{stock}</strong> units in inventory</> : <>{inventoryEntries.length} inventory {inventoryEntries.length === 1 ? 'item' : 'items'}</>}</span>{refunds.length > 0 && <span><strong>{refunds.length}</strong> refunds</span>}{typeof state.balance_cents === 'number' && <span>Balance <strong>{new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(state.balance_cents / 100)}</strong></span>}</div></div>
  </div>;
}

function CustomPreview({ currentCase, state, report, busy, onReproduce }: { currentCase: RepairCase; state: JsonObject; report: RepairReport | null; busy: boolean; onReproduce: () => void }) {
  return <div className="rx-custom-preview"><div className="rx-custom-heading"><div className="rx-empty-emblem"><Terminal size={26}/></div><div><h2>{currentCase.service || 'Your event handler'}</h2><p>{report ? 'State returned by your handler after execution.' : 'Your initial state, ready for the reproduction events.'}</p></div><Button className="rx-button-secondary" disabled={busy} onClick={onReproduce}><Play size={14}/>Run events</Button></div><div className="rx-custom-state"><span>Application state</span><pre>{stringify(state)}</pre></div><div className="rx-custom-events"><h3>Reproduction</h3><p>{currentCase.reproduction.length} {currentCase.reproduction.length === 1 ? 'event' : 'events'} in this case</p><pre>{stringify(currentCase.reproduction)}</pre></div></div>;
}

function AgentPanel({ provider, busy, events, repair, condition, setCondition, checkpoint, setCheckpoint, checkpoints, onConnect, caseRepairs, onSelect }: { provider: RepairState['provider']; busy: boolean; events: RepairEvent[]; repair?: Repair; condition: Condition; setCondition: (condition: Condition) => void; checkpoint: string; setCheckpoint: (value: string) => void; checkpoints: RepairCheckpoint[]; onConnect: () => void; caseRepairs: Repair[]; onSelect: (repair: Repair) => void }) {
  return <aside className="rx-agent-panel"><div className="rx-surface-heading"><div><Sparkles size={17}/><h2>Repair agent</h2></div>{busy ? <Tag tone="blue"><LoaderCircle size={11} className="rx-spin"/>Working</Tag> : <span className="rx-agent-idle">{repair ? 'Run complete' : 'Ready'}</span>}</div><div className="rx-agent-configuration"><label htmlFor="rx-condition">Intelligence</label><div className="rx-select-wrap"><select id="rx-condition" value={condition} onChange={event => setCondition(event.target.value as Condition)} disabled={busy}><option value="base">Base model</option><option value="memory">With training example memory</option><option value="learned" disabled={!checkpoints.length}>Your learned specialist</option></select><ChevronDown size={13}/></div>{condition === 'learned' && <select aria-label="Repair specialist checkpoint" value={checkpoint} onChange={event => setCheckpoint(event.target.value)} disabled={busy}>{checkpoints.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}<div className="rx-agent-model"><span className={provider.verified ? 'verified' : ''}/>{provider.model ? shorten(provider.model, 32) : 'River specialist'}{!provider.configured && <button onClick={onConnect}>Connect</button>}</div></div><div className="rx-agent-log" aria-live="polite">{events.length ? <EventLog events={events} busy={busy}/> : repair ? <div className="rx-agent-summary"><span className="rx-agent-summary-icon"><CheckCheck size={24}/></span><h3>{repair.origin === 'manual' ? 'Manual patch verified.' : 'Repair attempt complete.'}</h3><p>{repair.summary}</p><Status report={repair.report}/></div> : <div className="rx-agent-empty"><div className="rx-agent-orbit"><ReflexMark/><span/><span/></div><h3>A fix worth learning.</h3><p>Reproduce the failure. The agent inspects the handler, writes a patch, and runs the behavioral checks.</p><div className="rx-agent-empty-flow"><span><FileCode2 size={13}/>Read handler</span><ChevronRight size={11}/><span><Code2 size={13}/>Patch</span><ChevronRight size={11}/><span><CircleCheck size={13}/>Verify</span></div>{!provider.configured && <button onClick={onConnect} className="rx-agent-connect"><Unplug size={14}/>Connect River to generate a repair</button>}</div>}</div><div className="rx-agent-history"><div><h3>Saved attempts</h3><span>{caseRepairs.length}</span></div>{caseRepairs.length ? caseRepairs.slice(0, 3).map(item => <button key={item.id} onClick={() => onSelect(item)} className={item.id === repair?.id ? 'selected' : ''}><span className={didPass(item.report) ? 'pass' : 'fail'}>{item.human_feedback?.approved ? <CheckCheck size={14}/> : didPass(item.report) ? <Check size={14}/> : <X size={14}/>}</span><span><strong>{item.human_feedback?.approved ? 'Human approved' : item.machine_feedback?.approved ? 'Machine verified' : item.origin === 'manual' ? 'Manual patch' : humanize(item.condition || 'Base model')}</strong><small>{time(item.created_at)}{item.report ? ` · ${passedCount(item.report)}/${item.report.total} checks` : ''}</small></span><ChevronRight size={13}/></button>) : <p>Your verified attempts are saved here.</p>}</div></aside>;
}

function EventLog({ events, busy }: { events: RepairEvent[]; busy: boolean }) {
  return <div className="rx-event-log">{events.map((event, index) => {
    const failed = /fail|error|interrupt|stopped/.test(event.type) || event.status === 'failed' || event.training_eligible === false;
    let description = event.message || humanize(event.type);
    if (!event.message && event.type === 'curriculum_started') description = `Generating ${event.count} sample repairs, ${event.concurrency} at a time.`;
    if (!event.message && event.type === 'curriculum_case_started') description = `Repairing generated sample ${event.case_id || ''}.`;
    if (!event.message && event.type === 'curriculum_case_completed') description = `${event.completed}/${event.total} examples finished · ${event.passed}/${event.checks} checks passed for this sample. ${event.verified} machine verified; ${event.failed} failed.`;
    if (!event.message && /curriculum_(completed|stopped)/.test(event.type)) description = `${event.completed}/${event.requested} examples finished · ${event.verified} machine verified; ${event.failed} failed. Saved outcomes are retained.`;
    return <div className={`rx-event ${failed ? 'failed' : ''}`} key={`${event.type}-${index}`}><span className="rx-event-node">{failed ? <X size={11}/> : <Check size={11}/>}</span><div><span>{humanize(event.type)}</span><p>{description}</p></div></div>;
  })}{busy && <div className="rx-event-running"><LoaderCircle size={14} className="rx-spin"/>Executing…</div>}</div>;
}

function Verification({ report, expected, onEdit, onReproduce, busy }: { report: RepairReport | null; expected: string | string[]; onEdit: () => void; onReproduce: () => void; busy: boolean }) {
  const behavior = Array.isArray(expected) ? expected : expected ? [expected] : [];
  return <div className="rx-verification"><div className="rx-verification-main">{report ? <><div className="rx-verification-summary"><span className={`rx-verification-symbol ${didPass(report) ? 'pass' : 'fail'}`}>{didPass(report) ? <CheckCheck size={20}/> : <CircleAlert size={20}/>}</span><div><h3>{didPass(report) ? 'The behavior checks pass.' : 'Reproduced. Here’s what breaks.'}</h3><p>{passedCount(report)} of {report.total} checks pass{report.duration_ms != null ? ` in ${Math.round(report.duration_ms)} ms` : ''}. {didPass(report) ? 'Review the patch before accepting this repair.' : 'Repair the handler, then verify the same contract.'}</p></div>{!didPass(report) && <button onClick={onEdit}>Edit handler<ArrowUpRight size={14}/></button>}</div><div className="rx-check-list">{report.checks.map((check, index) => <div className="rx-check" key={`${check.name}-${index}`}><span className={check.passed ? 'pass' : 'fail'}>{check.passed ? <Check size={13}/> : <X size={13}/>}</span><strong>{humanize(check.name)}</strong><p>{typeof check.detail === 'string' ? check.detail : stringify(check.detail)}</p><span className={`rx-check-outcome ${check.passed ? 'pass' : 'fail'}`}>{check.passed ? 'Pass' : 'Fail'}</span></div>)}</div></> : <div className="rx-verification-empty"><span><FlaskConical size={27}/></span><div><h3>First, make the failure visible.</h3><p>Reproduce the issue to run the real handler against its expected behavior. Every check will report what happened.</p></div><Button className="rx-button-secondary" disabled={busy} onClick={onReproduce}><Play size={13}/>Run reproduction</Button></div>}</div><div className="rx-behavior-contract"><h3><ShieldIcon/>Behavior contract</h3>{behavior.length ? <ul>{behavior.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>The case’s expected state and responses define a passing repair.</p>}{report?.isolation && <details><summary>Execution boundary<ChevronDown size={11}/></summary><p>{typeof report.isolation === 'string' ? report.isolation : report.isolation.detail || report.isolation.kind || 'Local execution'}</p></details>}</div></div>;
}
function ShieldIcon() { return <svg width="14" height="16" viewBox="0 0 16 18" fill="none" aria-hidden="true"><path d="M8 1 14 4v5c0 4-6 7-6 7S2 13 2 9V4l6-3Z" stroke="currentColor" strokeWidth="1.4"/><path d="m5 8 2 2 4-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>; }

function CodeEditor({ value, onChange, filename, changed, onReset }: { value: string; onChange: (value: string) => void; filename: string; changed: boolean; onReset: () => void }) {
  const [scroll, setScroll] = useState(0);
  return <div className="rx-editor"><div className="rx-editor-heading"><span><FileCode2 size={13}/>{filename}</span><span>Editable Python handler</span>{changed && <button onClick={onReset}><RotateCcw size={12}/>Reset to original</button>}</div><div className="rx-editor-body"><div className="rx-editor-gutter" aria-hidden="true"><pre style={{ transform: `translateY(-${scroll}px)` }}>{value.split('\n').map((_, index) => index + 1).join('\n')}</pre></div><textarea aria-label="Repair handler source code" spellCheck={false} value={value} onChange={event => onChange(event.target.value)} onScroll={event => setScroll(event.currentTarget.scrollTop)} onKeyDown={event => { if (event.key === 'Tab') { event.preventDefault(); const target = event.currentTarget; const start = target.selectionStart; const next = `${value.slice(0, start)}    ${value.slice(target.selectionEnd)}`; onChange(next); requestAnimationFrame(() => { target.selectionStart = start + 4; target.selectionEnd = start + 4; }); } }} /></div><div className="rx-editor-foot"><span>apply(state, event) → response</span><span>{value.split('\n').length} lines</span></div></div>;
}
function PatchView({ diff, stale, onVerify, busy }: { diff?: string; stale: boolean; onVerify: () => void; busy: boolean }) {
  if (!diff) return <div className="rx-patch-empty"><GitCompareArrows size={25}/><div><h3>A patch starts with a change.</h3><p>Ask the agent for a repair or edit the handler code, then verify it to save a patch.</p></div></div>;
  return <div className="rx-patch-view">{stale && <div className="rx-stale-patch"><CircleAlert size={14}/><span>Your editor has changes beyond this saved patch.</span><button disabled={busy} onClick={onVerify}>Verify current code</button></div>}<pre>{diff.split('\n').map((line, index) => <span className={line.startsWith('+') && !line.startsWith('+++') ? 'added' : line.startsWith('-') && !line.startsWith('---') ? 'removed' : line.startsWith('@@') ? 'hunk' : ''} key={index}>{line || ' '}<br/></span>)}</pre></div>;
}
function AcceptRepair({ repair, source, busy, verifyBusy, onAccept, onVerify }: { repair?: Repair; source: string; busy: boolean; verifyBusy: boolean; onAccept: (reason: string) => Promise<boolean | undefined>; onVerify: () => void }) {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => { setReason(repair?.human_feedback?.reason || ''); }, [repair?.id, repair?.human_feedback?.reason]);
  const accepted = repair?.human_feedback?.approved && source === repair.human_feedback.code;
  const machineVerified = repair?.machine_feedback?.approved && source === repair.machine_feedback.code;
  const matches = !!repair && source === repair.code;
  const eligible = !!repair && didPass(repair.report) && matches;
  const save = async (event: FormEvent) => { event.preventDefault(); if (busy || !eligible || !reason.trim()) return; setSaving(true); await onAccept(reason.trim()); setSaving(false); };
  return <form className={`rx-accept-repair ${accepted ? 'accepted' : ''}`} onSubmit={event => void save(event)}><span className="rx-accept-icon">{accepted ? <CheckCheck size={19}/> : <Layers3 size={19}/>}</span><div className="rx-accept-copy"><strong>{accepted ? 'Human approved. Ready to learn from.' : machineVerified ? 'Machine-verified generated sample.' : 'Your judgment closes the loop.'}</strong><p>{accepted ? 'The patch, verification, and your reason are saved together.' : machineVerified ? 'This sample qualifies through executable checks. You can add your own review and approval.' : !repair ? 'Verify a repair, then accept it with a reason.' : !matches ? 'Verify your latest edits before accepting the repair.' : !didPass(repair.report) ? 'Resolve the failing checks before accepting this repair.' : 'Explain why this repair is right. That becomes the learning signal.'}</p></div>{accepted ? <Tag tone="green"><Check size={12}/>Experience saved</Tag> : eligible ? <div className="rx-accept-controls"><input aria-label="Why this repair is correct" placeholder="Why is this repair right?" value={reason} onChange={event => setReason(event.target.value)} required/><Button className="rx-button-dark" busy={saving} disabled={busy || !reason.trim()} type="submit"><CheckCheck size={15}/>Accept repair</Button></div> : repair && !matches ? <Button className="rx-button-secondary" disabled={verifyBusy} onClick={onVerify} type="button"><Play size={13}/>Verify edits</Button> : <Button className="rx-button-secondary" disabled type="button"><CheckCheck size={15}/>Accept repair</Button>}</form>;
}

function CurriculumControls({ busy, running, configured, machineVerified, onConnect, onGenerate }: { busy: boolean; running: boolean; configured: boolean; machineVerified: number; onConnect: () => void; onGenerate: (count: number, concurrency: number) => void }) {
  const [count, setCount] = useState('24');
  const [concurrency, setConcurrency] = useState('3');
  const valid = Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 24 && Number.isInteger(Number(concurrency)) && Number(concurrency) >= 1 && Number(concurrency) <= 4;
  const generate = (event: FormEvent) => {
    event.preventDefault();
    if (busy || !valid) return;
    if (!configured) { onConnect(); return; }
    onGenerate(Number(count), Number(concurrency));
  };
  return <section className="rx-curriculum-panel" aria-labelledby="rx-curriculum-title">
    <div className="rx-curriculum-copy"><span className="rx-curriculum-icon"><Sparkles size={20}/></span><div><h2 id="rx-curriculum-title">Build a practice set.</h2><p>Generate sample variants of six repair families. River writes each fix; executable checks determine which examples qualify for training.</p><span className="rx-curriculum-provenance">Generated samples · machine verified · {machineVerified} saved</span></div></div>
    <form className="rx-curriculum-form" onSubmit={generate}>
      <div className="rx-curriculum-fields"><label htmlFor="rx-example-count">Examples<input id="rx-example-count" type="number" min={1} max={24} step={1} value={count} onChange={event => setCount(event.target.value)} disabled={busy} required/></label><label htmlFor="rx-example-concurrency">At a time<input id="rx-example-concurrency" type="number" min={1} max={4} step={1} value={concurrency} onChange={event => setConcurrency(event.target.value)} disabled={busy} required/></label></div>
      <Button type="submit" className="rx-button-secondary" busy={running} disabled={busy || !valid}><Sparkles size={15}/>{configured ? 'Generate verified examples' : 'Connect River to generate'}</Button>
      <p>Uses River generation. Passing samples receive machine acceptance, separate from your approval. Training runs separately.</p>
    </form>
  </section>;
}

function LearningPanel({ state, busy, job, events, onConnect, onTrain, onGenerate, onEvaluate, onSelect, onBack }: { state: RepairState; busy: boolean; job: RepairJob | null; events: RepairEvent[]; onConnect: () => void; onTrain: (name: string) => void; onGenerate: (count: number, concurrency: number) => void; onEvaluate: (checkpoint: string) => void; onSelect: (repair: Repair) => void; onBack: () => void }) {
  const [name, setName] = useState('reflex-repairs-v1');
  const [checkpointId, setCheckpointId] = useState('');
  const [evaluationId, setEvaluationId] = useState('');
  const [copied, setCopied] = useState('');
  const [copyError, setCopyError] = useState('');
  const [savedLearningJob, setSavedLearningJob] = useState<RepairJob | null>(null);
  const [savedLogError, setSavedLogError] = useState('');
  const accepted = state.repairs.filter(item => item.human_feedback?.approved || item.machine_feedback?.approved);
  const eligible = state.stats.eligible;
  const trainingReady = eligible !== undefined && eligible >= 2 && !state.training_error;
  const selectedCheckpoint = state.checkpoints.find(item => item.id === checkpointId) || state.checkpoints[0];
  const evaluation = state.evaluations.find(item => item.id === evaluationId) || state.evaluations[0];
  const measuredCheckpoint = state.checkpoints.find(item => item.checkpoint === evaluation?.checkpoint);
  const latestLearningJob = job && /train|eval|curriculum/.test(job.kind || '') ? job : state.jobs.find(item => /train|eval|curriculum/.test(item.kind || ''));
  const learningJob = latestLearningJob && savedLearningJob?.id === latestLearningJob.id && TERMINAL.has(latestLearningJob.status) ? { ...latestLearningJob, events: latestLearningJob.events || savedLearningJob.events } : latestLearningJob;
  const learningRunning = !!learningJob && !TERMINAL.has(learningJob.status);
  const learningCompleted = learningJob?.status === 'completed' || learningJob?.status === 'complete';
  const learningEvents = learningJob?.id === job?.id && events.length ? events : learningJob?.events || [];
  const running = !!job && !TERMINAL.has(job.status);
  useEffect(() => {
    if (!latestLearningJob || !TERMINAL.has(latestLearningJob.status)) return;
    let cancelled = false;
    setSavedLogError('');
    void api<RepairJob>(`/jobs/${encodeURIComponent(latestLearningJob.id)}`).then(result => {
      if (!cancelled) setSavedLearningJob(result);
    }).catch(error => { if (!cancelled) setSavedLogError(`Saved log unavailable: ${messageOf(error)} Refresh the page to retry.`); });
    return () => { cancelled = true; };
  }, [latestLearningJob?.id, latestLearningJob?.status]);
  const copy = async (item: RepairCheckpoint) => { try { await navigator.clipboard.writeText(item.checkpoint); setCopied(item.id); setCopyError(''); window.setTimeout(() => setCopied(''), 2500); } catch { setCopyError('Clipboard access was blocked. Select the full checkpoint reference to copy it.'); } };
  return <div className="rx-learning-view"><div className="rx-learning-heading"><button className="rx-back-link" onClick={onBack}><ArrowLeft size={14}/>Back to workbench</button><h1>Better repairs, learned from real work.</h1><p>Accept a fix once. Train the specialist. Measure whether that judgment transfers to a new failure.</p></div><div className="rx-learning-grid"><section className="rx-accepted-panel"><div className="rx-surface-heading"><div><Layers3 size={17}/><h2>Training experience</h2></div><span className="rx-count-label">{accepted.length} {accepted.length === 1 ? 'repair' : 'repairs'}</span><a className="rx-plain-action" href="/api/repairs/export" download><ArrowDownToLine size={14}/>Export</a></div>{accepted.length ? <div className="rx-accepted-list">{accepted.map(item => <button key={item.id} onClick={() => onSelect(item)}><span className="rx-accepted-check"><CheckCheck size={17}/></span><div><h3>{item.title}</h3><p>{item.human_feedback?.reason || item.machine_feedback?.reason}</p><span>{item.human_feedback?.approved ? 'Human approved' : 'Machine verified · generated sample'}<span/>{passedCount(item.report)}/{item.report.total} checks pass</span></div><ChevronRight size={15}/></button>)}</div> : <div className="rx-learning-empty"><div className="rx-learning-illustration"><FileCode2 size={30}/><span><Check size={14}/></span></div><h3>Start with one repair you trust.</h3><p>Run the checks, inspect the patch, and accept it with your reason. You can also generate sample repairs and keep only those that pass the executable checks.</p><Button className="rx-button-secondary" onClick={onBack}>Open the workbench<ArrowRight size={14}/></Button></div>}<div className="rx-learning-data-note"><Database size={15}/><p>A training run freezes the code, behavior contract, and acceptance provenance into an immutable dataset.</p></div></section><section className="rx-train-panel"><div className="rx-surface-heading"><div><Zap size={17}/><h2>Train your specialist</h2></div><Tag>SFT</Tag></div><div className="rx-train-body"><div className="rx-training-lineage"><span><FileCode2 size={19}/></span><i/><span className="active"><ReflexMark/></span><i/><span><GitBranch size={20}/></span></div><h3>Keep the intelligence<br/>the work created.</h3><p>River updates the model’s weights using human-approved repairs and machine-verified samples.</p><label htmlFor="rx-checkpoint-name">Checkpoint name</label><input id="rx-checkpoint-name" value={name} maxLength={64} onChange={event => setName(event.target.value)} placeholder="reflex-repairs-v1"/><div className="rx-training-readiness"><span className={trainingReady ? 'ready' : ''}/>{state.training_error ? 'Resolve the dataset issue below' : eligible === undefined ? 'Checking training eligibility…' : trainingReady ? `${eligible} distinct examples ready` : `${eligible} eligible · at least 2 distinct examples required`}</div>{state.training_error && <p className="rx-dataset-error" role="alert">{state.training_error}</p>}{state.provider.configured ? <Button className="rx-button-primary rx-button-full" busy={running && !!job?.kind?.includes('train')} disabled={busy || !trainingReady || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name)} onClick={() => onTrain(name)}><Zap size={15}/>Learn from verified repairs</Button> : <Button className="rx-button-primary rx-button-full" onClick={onConnect}><Unplug size={15}/>Connect River to train</Button>}<p className="rx-training-note">Training starts only when you choose to run it.</p></div></section></div>
    <CurriculumControls busy={busy} running={running && job?.kind === 'repair_curriculum'} configured={state.provider.configured} machineVerified={state.stats.machine_verified ?? 0} onConnect={onConnect} onGenerate={onGenerate}/>{learningJob && <section className="rx-learning-job"><div className="rx-surface-heading"><div>{learningRunning ? <LoaderCircle size={16} className="rx-spin"/> : learningCompleted ? <CircleCheck size={16}/> : <CircleAlert size={16}/>}<h2>{learningJob.kind?.includes('curriculum') ? 'Generating verified examples' : learningJob.kind?.includes('train') ? 'Learning from verified repairs' : 'Held-out replay'}</h2></div><Tag tone={learningRunning ? 'blue' : learningCompleted ? 'green' : 'red'}>{humanize(learningJob.status)}</Tag></div>{learningJob.error && <p className="rx-learning-job-error">{learningJob.error}</p>}{savedLogError && <p className="rx-learning-job-error">{savedLogError}</p>}<EventLog events={learningEvents} busy={learningRunning}/></section>}
    <section className="rx-replay-panel"><div className="rx-replay-heading"><div><FlaskConical size={20}/><div><h2>The next failure is the real test.</h2><p>Same held-out cases. Base, memory, and your learned specialist.</p></div></div><div className="rx-replay-controls"><select aria-label="Checkpoint for repair evaluation" value={selectedCheckpoint?.id || ''} onChange={event => setCheckpointId(event.target.value)}>{!state.checkpoints.length && <option value="">No checkpoint yet</option>}{state.checkpoints.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><Button className="rx-button-dark" busy={running && !!job?.kind?.includes('eval')} disabled={busy || !selectedCheckpoint} onClick={() => state.provider.configured ? onEvaluate(selectedCheckpoint.id) : onConnect()}><Play size={13} fill="currentColor"/>Run held-out replay</Button></div></div>{evaluation && <div className="rx-replay-meta"><span className="rx-measured-checkpoint" title={evaluation.checkpoint}><GitBranch size={13}/>Measured: {measuredCheckpoint?.name || shorten(evaluation.checkpoint, 42)}</span><Tag tone={evaluation.status === 'completed' ? 'green' : 'red'}>{evaluation.status === 'completed' ? 'Completed measurement' : `${humanize(evaluation.status)} · partial results`}</Tag>{evaluation.matched_prompts && <span><CheckCheck size={13}/>Memory and learned prompts matched</span>}{state.evaluations.length > 1 && <select aria-label="Previous evaluation" value={evaluation.id} onChange={event => setEvaluationId(event.target.value)}>{state.evaluations.map((item, index) => <option key={item.id} value={item.id}>Run {state.evaluations.length - index} · {humanize(item.status)}</option>)}</select>}</div>}{evaluation?.error && <p className="rx-evaluation-error" role="alert">{evaluation.error}</p>}<div className="rx-replay-comparison">{(['base', 'memory', 'learned'] as const).map((condition, index) => {
      const result = evaluation?.conditions?.find(item => item.name === condition);
      const measured = !!result && result.total > 0;
      const value = measured ? Math.round((result.success_rate <= 1 ? result.success_rate * 100 : result.success_rate)) : null;
      return <div className={`rx-replay-row ${condition === 'learned' ? 'learned' : ''}`} key={condition}><span className="rx-condition-symbol">{index === 0 ? <Code2 size={17}/> : index === 1 ? <Layers3 size={17}/> : <ReflexMark/>}</span><div><strong>{condition === 'base' ? 'Base model' : condition === 'memory' ? 'With memory' : 'Learned specialist'}</strong><p>{condition === 'base' ? 'No training examples in context' : condition === 'memory' ? 'Training example memory added to context' : 'Same memory, updated model weights'}</p></div><div className="rx-replay-track"><span style={{ width: `${value ?? 0}%` }}/></div><div className="rx-replay-score"><strong>{value === null ? '—' : `${value}%`}</strong><span>{measured ? `${result.passed}/${result.total} repairs pass` : 'Not measured'}</span></div></div>;
    })}</div>{evaluation ? <EvaluationEvidence evaluation={evaluation}/> : <p className="rx-replay-empty-note">No scores are prefilled. Train a checkpoint and run the replay to measure actual repair success.</p>}</section>
    {state.checkpoints.length > 0 && <section className="rx-checkpoints-panel"><div className="rx-surface-heading"><div><GitBranch size={17}/><h2>Your checkpoints</h2></div><span className="rx-count-label">{state.checkpoints.length}</span></div>{state.checkpoints.map(item => <div className="rx-checkpoint-row" key={item.id}><span className="rx-checkpoint-icon"><GitBranch size={21}/></span><div><h3>{item.name}</h3><p>{item.example_count} training examples · {humanize(item.method || 'sft')}</p><code>{item.checkpoint}</code></div><div className="rx-checkpoint-actions"><button onClick={() => void copy(item)}>{copied === item.id ? <Check size={13}/> : <Copy size={13}/>} {copied === item.id ? 'Copied' : 'Copy reference'}</button>{item.dataset_hash && <a href={`/api/datasets/${encodeURIComponent(item.dataset_hash)}/export`} download><Database size={13}/>Training snapshot</a>}<a href="https://console.river.ai/" target="_blank" rel="noreferrer"><ArrowDownToLine size={13}/>Download weights<ExternalLink size={11}/></a></div></div>)}{copyError && <p className="rx-copy-error">{copyError}</p>}<p className="rx-checkpoint-foot">Download the checkpoint from River Console to keep a local copy of your trained weights.</p></section>}
  </div>;
}

function EvaluationEvidence({ evaluation }: { evaluation: RepairEvaluation }) {
  const [open, setOpen] = useState(false);
  return <div className="rx-replay-evidence"><button onClick={() => setOpen(!open)} aria-expanded={open}><FileCode2 size={14}/>Inspect the executed cases<ChevronDown size={14}/></button>{open && <div className="rx-evidence-results">{evaluation.conditions.flatMap(condition => condition.results.map((result, index) => <div key={`${condition.name}-${index}`}><span className={didPass(result.report) ? 'pass' : 'fail'}>{didPass(result.report) ? <Check size={13}/> : <X size={13}/>}</span><div><strong>{result.title}</strong><p>{humanize(condition.name)}{result.report ? ` · ${passedCount(result.report)}/${result.report.total} checks pass` : ''}{result.error ? ` · ${result.error}` : ''}</p></div>{result.prompt_hash && <code title={result.prompt_hash}>{shorten(result.prompt_hash, 17)}</code>}</div>))}</div>}</div>;
}

function NewCaseModal({ onClose, onCreate }: { onClose: () => void; onCreate: (body: unknown) => Promise<void> }) {
  const [title, setTitle] = useState('');
  const [service, setService] = useState('');
  const [description, setDescription] = useState('');
  const [source, setSource] = useState('');
  const [initial, setInitial] = useState('{}');
  const [events, setEvents] = useState('[]');
  const [expected, setExpected] = useState('{}');
  const [results, setResults] = useState('[]');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    let body: unknown;
    try {
      const initialState = JSON.parse(initial), eventList = JSON.parse(events), expectedState = JSON.parse(expected), expectedResults = JSON.parse(results);
      if (!initialState || typeof initialState !== 'object' || Array.isArray(initialState)) throw new Error('Initial state must be a JSON object.');
      if (!expectedState || typeof expectedState !== 'object' || Array.isArray(expectedState)) throw new Error('Expected state must be a JSON object.');
      if (!Array.isArray(eventList) || !eventList.length || eventList.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('Reproduction events must be a nonempty JSON array of objects.');
      if (!Array.isArray(expectedResults)) throw new Error('Expected responses must be a JSON array.');
      body = { title: title.trim(), service: service.trim() || 'Custom handler', description: description.trim(), source, initial_state: initialState, events: eventList, expected_state: expectedState, expected_results: expectedResults };
    } catch (err) { setError(err instanceof SyntaxError ? `Check your JSON: ${err.message}` : messageOf(err)); return; }
    setSaving(true);
    try { await onCreate(body); } catch (err) { setError(messageOf(err)); } finally { setSaving(false); }
  };
  return <Modal title="Bring your own failure." subtitle="Turn a reproducible event-handler bug into a verified repair and a learning example." wide onClose={onClose}><form className="rx-new-case-form" onSubmit={event => void submit(event)}>{error && <div className="rx-alert" role="alert"><CircleAlert size={16}/><p>{error}</p></div>}<div className="rx-intake-row"><label>What breaks?<input autoComplete="off" placeholder="A retried webhook reserves stock twice" value={title} onChange={event => setTitle(event.target.value)} required maxLength={200}/></label><label>Service<input placeholder="Inventory" value={service} onChange={event => setService(event.target.value)} maxLength={100}/></label></div><label>Expected behavior<textarea rows={2} placeholder="Repeated delivery of the same event should not change inventory a second time." value={description} onChange={event => setDescription(event.target.value)} required/></label><div className="rx-intake-code-label"><label htmlFor="rx-new-handler">Python handler</label><label className="rx-file-upload"><FileCode2 size={13}/>Open .py file<input type="file" accept=".py,text/x-python,text/plain" onChange={async event => { const file = event.target.files?.[0]; if (file) { if (file.size > 200000) setError('Choose a handler smaller than 200 KB.'); else setSource(await file.text()); } }}/></label></div><textarea id="rx-new-handler" className="rx-intake-code" spellCheck={false} rows={9} placeholder={'def apply(state, event):\n    # Mutate the JSON state and return a JSON response.\n    ...'} value={source} onChange={event => setSource(event.target.value)} required/><p className="rx-intake-boundary"><Code2 size={14}/>This workspace executes a single <code>apply(state, event)</code> handler with JSON inputs. Use the Repository tab to inspect a Python source file and execute its regression tests.</p><div className="rx-intake-json-grid"><label>Initial state<span>The object passed to the first event.</span><textarea spellCheck={false} rows={5} value={initial} onChange={event => setInitial(event.target.value)} required/></label><label>Reproduction events<span>Events, in the order they should execute.</span><textarea spellCheck={false} rows={5} value={events} onChange={event => setEvents(event.target.value)} required/></label><label>Expected final state<span>The exact state after all events.</span><textarea spellCheck={false} rows={5} value={expected} onChange={event => setExpected(event.target.value)} required/></label><label>Expected responses<span>One expected return value per event.</span><textarea spellCheck={false} rows={5} value={results} onChange={event => setResults(event.target.value)} required/></label></div><div className="rx-intake-footer"><p>Your handler stays local until you ask River to repair it or include an accepted repair in training.</p><Button type="submit" className="rx-button-primary" busy={saving} disabled={!title.trim() || !source.trim()}><Plus size={15}/>Create repair case</Button></div></form></Modal>;
}
