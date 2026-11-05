import { createRoot } from 'react-dom/client';
import './theme';
import './styles/base.css';
import './styles/layout.css';
import './styles/camera.css';
import './styles/calibration.css';
import './styles/responsive.css';
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
