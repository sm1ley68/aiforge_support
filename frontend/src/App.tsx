import { NavigationDemo } from './NavigationDemo';
import type { NavigationLayout } from './NavigationDemo';
import { OperatorWorkspace } from './OperatorWorkspace';

export function App({ navigation }: { navigation?: NavigationLayout }) {
  return navigation ? <NavigationDemo navigation={navigation} /> : <OperatorWorkspace />;
}
