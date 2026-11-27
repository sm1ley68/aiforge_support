import { NavigationDemo } from './NavigationDemo';
import type { NavigationLayout } from './NavigationDemo';
import { OperatorWorkspace } from './OperatorWorkspace';
import { LiveStoreAdvisor } from './LiveStoreAdvisor';

export function App({ navigation }: { navigation?: NavigationLayout }) {
  const view = new URLSearchParams(window.location.search).get('view');
  if (view === 'chat' || view === 'store') return <LiveStoreAdvisor />;
  return navigation ? <NavigationDemo navigation={navigation} /> : <OperatorWorkspace />;
}
