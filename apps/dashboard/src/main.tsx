import { createRoot } from 'react-dom/client';
import './theme';
import './styles/base.css';
import './styles/layout.css';
import './styles/camera.css';
import './styles/calibration.css';
import './styles/responsive.css';
import { DashboardProvider } from './dashboard';
import App from './App';
createRoot(document.getElementById('root')!).render(
	<DashboardProvider>
		<App />
	</DashboardProvider>,
);
