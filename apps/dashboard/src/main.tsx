import { createRoot } from 'react-dom/client';
import './index.css';
import './theme';
import { QueryClientProvider } from '@tanstack/react-query';
import { DashboardProvider } from './dashboard';
import { queryClient } from './queries';
import App from './App';
createRoot(document.getElementById('root')!).render(
	<QueryClientProvider client={queryClient}>
		<DashboardProvider>
			<App />
		</DashboardProvider>
	</QueryClientProvider>,
);
