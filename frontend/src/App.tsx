import { NavigationDemo } from './NavigationDemo';
import type { NavigationLayout } from './NavigationDemo';
import { OperatorWorkspace } from './OperatorWorkspace';
import { LiveStoreAdvisor } from './LiveStoreAdvisor';
import { ProductEntry } from './ProductEntry';

export function App({ navigation }: { navigation?: NavigationLayout }) {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view');
  const offer = params.get('offer');
  if (view === 'product') return <ProductEntry offerId={offer || '473583'} openChat={false} />;
  if (view === 'chat' || view === 'store') {
    return offer ? <ProductEntry offerId={offer} openChat /> : <LiveStoreAdvisor />;
  }
  return navigation ? <NavigationDemo navigation={navigation} /> : <OperatorWorkspace />;
}
