import { useEffect, useState } from 'react';
import LegacyReviewWorkspace from './LegacyReviewWorkspace';
import RepairWorkbench from './RepairWorkbench';

export default function App() {
  const [legacy, setLegacy] = useState(window.location.hash === '#review');
  useEffect(() => {
    const change = () => setLegacy(window.location.hash === '#review');
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  if (legacy) return <><button className="rx-legacy-return" onClick={() => { window.location.hash = 'repair'; }}>Back to repair workbench</button><LegacyReviewWorkspace /></>;
  return <RepairWorkbench onLegacy={() => { window.location.hash = 'review'; }} />;
}
