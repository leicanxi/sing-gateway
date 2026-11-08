import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AccountPage } from './AccountPage';
import '../styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');

createRoot(root).render(
  <StrictMode>
    <AccountPage />
  </StrictMode>,
);
