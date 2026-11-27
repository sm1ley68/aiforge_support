import { NavigationDemo } from './NavigationDemo';
import type { NavigationLayout } from './NavigationDemo';
import { OperatorWorkspace } from './OperatorWorkspace';
import { StoreAdvisor } from './StoreAdvisor';

export function App({ navigation }: { navigation?: NavigationLayout }) {
  const view = new URLSearchParams(window.location.search).get('view');
  if (view === 'chat' || view === 'store') return <StoreAdvisor />;
  return navigation ? <NavigationDemo navigation={navigation} /> : <OperatorWorkspace />;
}
