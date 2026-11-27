import { OperatorWorkspace } from './OperatorWorkspace';
import { LiveStoreAdvisor } from './LiveStoreAdvisor';

export function App() {
  const view = new URLSearchParams(window.location.search).get('view');
  return view === 'chat' || view === 'store' ? <LiveStoreAdvisor /> : <OperatorWorkspace />;
}
