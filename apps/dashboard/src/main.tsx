import { createRoot } from 'react-dom/client';
import './index.css';
import './theme';
import { QueryClientProvider } from '@tanstack/react-query';
import { createRouter, RouterProvider } from '@tanstack/react-router';
import { DashboardProvider } from './dashboard';
import { queryClient } from './queries';
import { routeTree } from './routeTree.gen';
const router = createRouter({ routeTree });
declare module '@tanstack/react-router' {
	interface Register {
		router: typeof router;
	}
}
createRoot(document.getElementById('root')!).render(
	<QueryClientProvider client={queryClient}>
		<DashboardProvider>
			<RouterProvider router={router} />
		</DashboardProvider>
	</QueryClientProvider>,
);
