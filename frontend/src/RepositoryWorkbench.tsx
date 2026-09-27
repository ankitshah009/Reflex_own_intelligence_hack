import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowDownToLine, ArrowRight, Check, CheckCheck, ChevronRight, CircleAlert, Code2, FileCode2, FileSearch, FolderGit2, GitCompareArrows, LoaderCircle, Play, RotateCcw, Sparkles, Terminal, X } from 'lucide-react';
import { api, post } from './api';
import type { RepairEvent, RepairJob, RepairState } from './repairTypes';
import './repository.css';

type RepositoryCase = {
  id: string; relative_file: string; test_path: string; source: string; test_content: string;
  source_hash: string; test_hash: string; snapshot_hash: string;
  snapshot_manifest: { path: string; sha256: string; bytes: number }[];
  created_at: string; include_tests_allowed?: boolean; test_content_redacted?: boolean;
};
type RepositoryReport = {
  status: string; passed: number; total: number; skipped: number; exit_code?: number | null;
  checks: { name: string; passed: boolean; status?: string; detail?: string }[];
  stdout: string; stderr: string; diff: string; code_hash: string; error?: string;
  duration_ms?: number; isolation?: { kind?: string; enforced?: boolean };
};
type RepositoryResult = {
  id: string; job_id: string; case_id: string; relative_file: string; test_path: string;
  code: string; summary: string; diff: string; report: RepositoryReport;
  baseline_report?: RepositoryReport; model?: string; origin?: string;
};
type RepositoryState = { cases: RepositoryCase[]; jobs: RepairJob[] };
type RepositoryRun = { case_id: string; instruction: string; include_tests: boolean; code?: string };
type Props = {
  busy: boolean; job: RepairJob | null; events: RepairEvent[];
  provider: RepairState['provider']; onConnect: () => void;
  onRun: (body: RepositoryRun) => void; onResumeJob: (job: RepairJob) => void;
};
const finished = (status: string) => ['completed', 'complete', 'failed', 'error', 'interrupted', 'cancelled'].includes(status);
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);
const cleanLabel = (label: string) => label.replace(/[_-]/g, ' ').replace(/^./, char => char.toUpperCase());
const passed = (report?: RepositoryReport | null) => !!report && report.status === 'passed' && report.passed > 0 && report.passed + report.skipped === report.total;
const reportLabel = (report?: RepositoryReport | null) => !report ? 'Not run' : report.total ? `${report.passed}/${report.total} passed` : cleanLabel(report.status);

export default function RepositoryWorkbench({ busy, job, events, provider, onConnect, onRun, onResumeJob }: Props) {
  const [cases, setCases] = useState<RepositoryCase[]>([]);
  const [savedJobs, setSavedJobs] = useState<RepairJob[]>([]);
  const [current, setCurrent] = useState<RepositoryCase | null>(null);
  const [relativeFile, setRelativeFile] = useState('backend/reflex/curriculum.py');
  const [testPath, setTestPath] = useState('tests/test_curriculum.py');
  const [instruction, setInstruction] = useState('');
  const [includeTests, setIncludeTests] = useState(false);
  const [source, setSource] = useState('');
  const [baseline, setBaseline] = useState<RepositoryReport | null>(null);
  const [result, setResult] = useState<RepositoryResult | null>(null);
  const [tab, setTab] = useState<'checks' | 'source' | 'diff' | 'output'>('checks');
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const currentId = useRef('');
  const loadedJob = useRef('');
  const resumeJob = useRef(onResumeJob);
  resumeJob.current = onResumeJob;
  currentId.current = current?.id || '';
  const repositoryJob = !!job?.kind?.startsWith('repository');
  const caseJob = repositoryJob && job?.payload?.case_id === current?.id;
  const running = !!job && caseJob && !finished(job.status);
  const disabled = busy || !!pending;
  const localBusy = running || !!pending;
  const resultJob = caseJob ? job : savedJobs.find(item => item.payload?.case_id === current?.id);
  const verified = result && result.code === source ? result.report : null;
  const visibleReport = verified || baseline;
  const edited = !!current && source !== current.source;
  const changedSelection = !!current && (relativeFile !== current.relative_file || testPath !== current.test_path);

  const selectCase = useCallback((item: RepositoryCase) => {
    setCurrent(item); setRelativeFile(item.relative_file); setTestPath(item.test_path);
    setSource(item.source); setIncludeTests(false); setResult(null); setBaseline(null); setError(''); setTab('source');
    loadedJob.current = '';
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api<RepositoryState>('/repository/state').then(next => {
      if (cancelled) return;
      setCases(next.cases || []); setSavedJobs(next.jobs || []);
      const active = next.jobs?.find(item => !finished(item.status));
      const initial = next.cases?.find(item => item.id === active?.payload?.case_id) || next.cases?.[0];
      if (initial) selectCase(initial);
      if (active) resumeJob.current(active);
      setLoaded(true);
    }).catch(err => { if (!cancelled) { setError(errorMessage(err)); setLoaded(true); } });
    return () => { cancelled = true; };
  }, [selectCase]);

  useEffect(() => {
    if (!resultJob || !finished(resultJob.status) || loadedJob.current === resultJob.id) return;
    if (!['completed', 'complete'].includes(resultJob.status)) { setError(resultJob.error || 'The repository run stopped. Its execution log is available below.'); return; }
    let cancelled = false;
    const expectedCase = current?.id;
    void api<RepositoryResult>(`/repository/repairs/${encodeURIComponent(resultJob.id)}`).then(next => {
      if (cancelled || currentId.current !== expectedCase) return;
      loadedJob.current = resultJob.id;
      setResult(next); setSource(next.code); setBaseline(next.baseline_report || null);
      setTab('checks'); setError('');
    }).catch(err => { if (!cancelled) setError(errorMessage(err)); });
    return () => { cancelled = true; };
  }, [resultJob?.id, resultJob?.status, current?.id]);

  useEffect(() => {
    if (!caseJob) return;
    const reproduced = events.find(event => event.type === 'reproduced' && event.report);
    if (reproduced?.report) setBaseline(reproduced.report as RepositoryReport);
  }, [caseJob, events]);

  const inspect = async (event: FormEvent) => {
    event.preventDefault();
    setPending('inspect'); setError('');
    try {
      const next = await post<RepositoryCase>('/repository/inspect', { relative_file: relativeFile.trim(), test_path: testPath.trim() });
      selectCase(next); setCases(items => [next, ...items.filter(item => item.id !== next.id)]);
    } catch (err) { setError(errorMessage(err)); }
    finally { setPending(''); }
  };
  const reproduce = async () => {
    if (!current) return;
    setPending('reproduce'); setError('');
    try {
      const report = await post<RepositoryReport>('/repository/reproduce', { case_id: current.id }, 60000);
      setBaseline(report); setTab('checks');
    } catch (err) { setError(errorMessage(err)); }
    finally { setPending(''); }
  };
  const repair = (manual = false) => {
    if (!current || disabled) return;
    if (!manual && !provider.configured) { onConnect(); return; }
    setError('');
    onRun({ case_id: current.id, instruction: instruction.trim() || 'Fix the failure demonstrated by the selected regression tests. Preserve existing behavior.', include_tests: includeTests, ...(manual ? { code: source } : {}) });
  };

  return <div className="rx-repository">
    <div className="rx-repository-heading"><div><div className="rx-repository-location"><FolderGit2 size={15}/><span>Local repository</span><ChevronRight size={12}/><span>Python</span></div><h1>Repair the code you ship.</h1><p>Choose a source file and its tests. Reproduce the failure, review the repair, and take the patch back to your repo.</p></div><span className="rx-repository-scope"><span/>Your workspace</span></div>
    {error && <div className="rx-alert" role="alert"><CircleAlert size={17}/><p>{error}</p><button className="rx-icon-button" aria-label="Dismiss repository error" onClick={() => setError('')}><X size={16}/></button></div>}
    {busy && !running && <div className="rx-background-job"><LoaderCircle size={14} className="rx-spin"/><span>Another workspace run is active. File inspection and local tests are still available.</span></div>}

    <div className="rx-repository-layout">
      <aside className="rx-repository-setup">
        <form onSubmit={event => void inspect(event)} className="rx-repository-files">
          <div className="rx-repository-section-title"><FileSearch size={18}/><h2>Start with your code</h2></div>
          <label htmlFor="rx-repo-source">Source file<span>Relative to this project</span></label>
          <input id="rx-repo-source" autoComplete="off" spellCheck={false} required pattern="backend/.+\.py" value={relativeFile} maxLength={500} disabled={localBusy} onChange={event => setRelativeFile(event.target.value)} placeholder="backend/service.py"/>
          <label htmlFor="rx-repo-tests">Regression tests</label>
          <input id="rx-repo-tests" autoComplete="off" spellCheck={false} required pattern="tests/.+\.py" value={testPath} maxLength={500} disabled={localBusy} onChange={event => setTestPath(event.target.value)} placeholder="tests/test_service.py"/>
          <button type="submit" className="rx-button rx-button-secondary" disabled={localBusy || !relativeFile.trim() || !testPath.trim()}>{pending === 'inspect' ? <LoaderCircle size={15} className="rx-spin"/> : <FileSearch size={15}/>} {pending === 'inspect' ? 'Reading files…' : current ? 'Inspect files again' : 'Inspect files'}</button>
          <p>Tests run against a disposable copy. Download the proposed patch when you’re ready to use it.</p>
        </form>
        <div className="rx-repository-instruction"><label htmlFor="rx-repo-instruction">What needs fixing?<span>Optional context for the agent</span></label><textarea id="rx-repo-instruction" value={instruction} maxLength={8000} onChange={event => setInstruction(event.target.value)} disabled={disabled} placeholder="A retry creates a duplicate record. Keep the first result and make retries safe." rows={4}/><label className="rx-repository-consent"><input type="checkbox" checked={includeTests} onChange={event => setIncludeTests(event.target.checked)} disabled={disabled || current?.include_tests_allowed === false}/><span>Include test source in the River request<small>{current?.include_tests_allowed === false ? 'Test source contains credential-like text and stays local.' : 'Source code and your instructions are sent when you request a repair.'}</small></span></label></div>
        <div className="rx-repository-history"><h3>Inspected files<span>{cases.length}</span></h3>{!loaded ? <p>Loading saved snapshots…</p> : !cases.length ? <p>Your inspected files will appear here.</p> : cases.slice(0, 6).map(item => <button key={item.id} className={item.id === current?.id ? 'selected' : ''} disabled={localBusy} onClick={() => selectCase(item)}><FileCode2 size={15}/><span><strong>{item.relative_file.split('/').pop()}</strong><small>{item.test_path.split('/').pop()}</small></span><ChevronRight size={13}/></button>)}</div>
      </aside>

      <section className="rx-repository-workspace">
        <div className="rx-repository-steps" aria-label="Repair progress">
          <div className={current ? 'ready' : ''}><span>{current ? <Check size={14}/> : '1'}</span><div><strong>Inspect</strong><small>{current ? `${current.snapshot_manifest.length} files in snapshot` : 'Choose a file and tests'}</small></div></div><ChevronRight size={15}/>
          <div className={baseline ? 'ready' : ''}><span>{baseline ? <Check size={14}/> : '2'}</span><div><strong>Reproduce</strong><small>{baseline ? reportLabel(baseline) : 'Run the original tests'}</small></div></div><ChevronRight size={15}/>
          <div className={verified ? passed(verified) ? 'ready' : 'failed' : ''}><span>{verified ? passed(verified) ? <Check size={14}/> : <X size={14}/> : '3'}</span><div><strong>Repair & verify</strong><small>{verified ? reportLabel(verified) : 'Inspect the actual result'}</small></div></div>
        </div>
        {!current ? <div className="rx-repository-empty"><div className="rx-repository-file-art" aria-hidden="true"><div><span/><span/><span/><span/><span/></div><span><FileCode2 size={25}/></span></div><h2>A real file. A reproducible failure.</h2><p>Point Reflex at the Python code you’re working on and the test file that defines the expected behavior.</p><div><Code2 size={14}/><code>backend/**/*.py</code><ArrowRight size={14}/><CheckCheck size={14}/><code>tests/**/*.py</code></div></div> : <>
          <div className="rx-repository-file-heading"><div><FileCode2 size={18}/><div><strong>{current.relative_file}</strong><small>{current.test_path}</small></div></div><div className="rx-repository-file-actions"><button type="button" className="rx-button rx-button-secondary" disabled={localBusy || changedSelection} onClick={() => void reproduce()}>{pending === 'reproduce' ? <LoaderCircle size={14} className="rx-spin"/> : <RotateCcw size={14}/>} {pending === 'reproduce' ? 'Running tests…' : 'Reproduce'}</button><button type="button" className="rx-button rx-button-primary" disabled={disabled || changedSelection || passed(baseline)} onClick={() => repair()}>{running ? <LoaderCircle size={14} className="rx-spin"/> : <Sparkles size={14}/>} {running ? 'Repairing…' : 'Ask agent to repair'}</button></div></div>
          {passed(baseline) && <p className="rx-repository-selection-note"><CheckCheck size={14}/>The selected tests already pass. Choose a failing regression for an agent repair, or edit and verify the working file.</p>}
          {changedSelection && <p className="rx-repository-selection-note"><CircleAlert size={14}/>The file paths changed. Inspect them to start a new snapshot.</p>}
          <div className="rx-repository-tabs" role="tablist" aria-label="Repository repair details">{([['checks', 'Test results', CheckCheck], ['source', 'Source', FileCode2], ['diff', 'Patch', GitCompareArrows], ['output', 'Output', Terminal]] as const).map(([key, label, Icon]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}><Icon size={14}/>{label}{key === 'source' && edited && <span className="rx-repository-edited" title="Working file has changed"/>}</button>)}</div>
          <div className="rx-repository-detail" role="tabpanel">
            {tab === 'source' && <><div className="rx-repository-editor-heading"><span>{edited ? 'Working file' : 'Inspected source'}{result && result.code !== source && ' · edited since verification'}</span><button disabled={disabled || !edited} onClick={() => { setSource(current.source); setResult(null); }}>Reset to snapshot<RotateCcw size={12}/></button></div><textarea className="rx-repository-editor" aria-label="Repository working source" value={source} maxLength={262144} onChange={event => setSource(event.target.value)} disabled={running} spellCheck={false} autoCapitalize="off" autoCorrect="off"/><div className="rx-repository-editor-footer"><span>{source.split('\n').length} lines</span><button className="rx-button rx-button-secondary rx-button-small" disabled={disabled || !source.trim() || changedSelection} onClick={() => repair(true)}><Play size={12}/>Verify working file</button></div></>}
            {tab === 'diff' && (result?.diff && result.code === source ? <pre className="rx-repository-diff" aria-label="Unified patch">{result.diff.split('\n').map((line, index) => <span className={line.startsWith('+') && !line.startsWith('+++') ? 'added' : line.startsWith('-') && !line.startsWith('---') ? 'removed' : line.startsWith('@@') ? 'range' : ''} key={index}>{line || ' '}<br/></span>)}</pre> : <div className="rx-repository-detail-empty"><GitCompareArrows size={27}/><h3>{result && result.code !== source ? 'Verify your latest edit.' : 'Your proposed patch will appear here.'}</h3><p>{result && result.code !== source ? 'The working file changed after the last run. Verify it to produce a matching diff.' : 'Ask the agent for a repair, or edit the source and verify the working file.'}</p></div>)}
            {tab === 'output' && <div className="rx-repository-output"><h3>{verified ? 'Candidate test output' : 'Original test output'}</h3><pre>{visibleReport ? [visibleReport.stdout, visibleReport.stderr].filter(Boolean).join('\n') || 'The test process returned no console output.' : 'Reproduce the issue to see the actual pytest output.'}</pre></div>}
            {tab === 'checks' && <><div className="rx-repository-comparison"><ReportScore label="Original file" report={baseline}/><ArrowRight size={18}/><ReportScore label="Working patch" report={verified}/></div>{verified?.error || baseline?.error && !verified ? <p className="rx-repository-report-error">{verified?.error || baseline?.error}</p> : null}{visibleReport ? <div className="rx-repository-checks">{visibleReport.checks.map((check, index) => <div key={`${check.name}-${index}`} className={check.passed ? 'pass' : check.status === 'skipped' ? 'skipped' : 'fail'}><span>{check.passed ? <Check size={14}/> : check.status === 'skipped' ? <span>−</span> : <X size={14}/>}</span><div><strong>{check.name}</strong>{check.detail && <p>{check.detail}</p>}</div><small>{check.status === 'skipped' ? 'Skipped' : check.passed ? 'Passed' : 'Failed'}</small></div>)}{!visibleReport.total && <p>No test results were produced. Read the execution output for details.</p>}</div> : <div className="rx-repository-detail-empty"><Terminal size={27}/><h3>Run the original tests first.</h3><p>The actual pass and fail results establish what the repair needs to change.</p><button className="rx-button rx-button-secondary" disabled={localBusy || changedSelection} onClick={() => void reproduce()}><Play size={13}/>Reproduce failure</button></div>}</>}
          </div>
          {result && <div className="rx-repository-result"><div><span className={passed(verified) ? 'pass' : ''}>{passed(verified) ? <CheckCheck size={19}/> : <GitCompareArrows size={19}/>}</span><div><h3>{verified ? passed(verified) ? 'Tests pass for this patch.' : 'The repair needs another look.' : 'Your working file has changed.'}</h3><p>{result.summary || 'Inspect the diff and execution results before applying the patch.'}</p></div></div>{result.diff && result.code === source && <a className="rx-button rx-button-secondary" href={`/api/repository/repairs/${encodeURIComponent(result.job_id || result.id)}/patch`} download><ArrowDownToLine size={14}/>Download patch</a>}</div>}
          <footer className="rx-repository-proof"><span title={current.snapshot_hash}>Snapshot <code>{current.snapshot_hash.slice(0, 12)}</code></span>{visibleReport?.isolation?.enforced && <span><CheckCheck size={13}/>Isolated execution</span>}{visibleReport?.duration_ms !== undefined && <span>{(visibleReport.duration_ms / 1000).toFixed(2)} s</span>}<span>Original files stay in your workspace</span></footer>
        </>}
      </section>
    </div>
    {caseJob && events.length > 0 && <section className="rx-repository-runlog"><div><Terminal size={16}/><h2>Execution log</h2>{running && <span><LoaderCircle size={13} className="rx-spin"/>Running</span>}</div><ol>{events.map((event, index) => <li className={/fail|error|interrupt/.test(event.type) ? 'error' : ''} key={`${event.type}-${index}`}><span/><div><strong>{cleanLabel(event.type)}</strong>{event.message && <p>{event.message}</p>}</div></li>)}</ol></section>}
  </div>;
}

function ReportScore({ label, report }: { label: string; report?: RepositoryReport | null }) {
  return <div className={`rx-repository-score ${report ? passed(report) ? 'pass' : 'fail' : ''}`}><span>{label}</span><strong>{reportLabel(report)}</strong><small>{!report ? 'Awaiting execution' : report.skipped ? `${report.skipped} skipped` : report.exit_code != null ? `Process exit code ${report.exit_code}` : cleanLabel(report.status)}</small></div>;
}
