import { createRoot } from 'react-dom/client';
import { MotionConfig } from 'motion/react';
import { App } from './App';
import { NavigationPreview } from './NavigationPreview';
import './styles.css';
import './navigation-preview.css';
import './ascii-workspace.css';
import './operator-workspace.css';

const preview = import.meta.env.DEV && new URLSearchParams(window.location.search).get('nav-preview');
const navigation = preview === 'integrated' || preview === 'compact' || preview === 'left' ? preview : undefined;

createRoot(document.getElementById('root')!).render(
  <MotionConfig reducedMotion="user">
    {preview === 'compare' ? <NavigationPreview /> : <App navigation={navigation} />}
  </MotionConfig>,
);
