import { createContext, useContext, useEffect, useRef, useState, useCallback, useMemo, type ReactNode } from 'react';
import { api, submit } from './api';
import { initialStatus, type Mutate, type Status } from './types';
import { PreviewStore } from './previews';

interface Dashboard {
	selections: { capture: Set<string>; results: Set<string>; history: Map<string, Set<string>> };
	read: () => Status;
	status: Status;
	serviceError: string;
	previews: PreviewStore;
	message: string;
	announce: (message: string) => void;
	refresh: () => Promise<Status>;
	mutate: Mutate;
}
const Context = createContext<Dashboard | null>(null);
export function DashboardProvider({ children }: { children: ReactNode }) {
	const [status, setStatus] = useState(initialStatus),
		[serviceError, setServiceError] = useState(''),
		[message, announce] = useState('');
	const [selections] = useState(() => ({
		capture: new Set<string>(),
		results: new Set<string>(),
		history: new Map<string, Set<string>>(),
	}));
	const session = useRef<{ csrf: string } | null>(null);
	const [previews] = useState(() => new PreviewStore());
	const snapshot = useRef(status);
	const read = useCallback(() => snapshot.current, []);
	const refresh = useCallback(async () => {
		const next = await api<Status>('/api/status');
		snapshot.current = next;
		setStatus(next);
		return next;
	}, []);
	const mutate: Mutate = useCallback(
		async (operation, payload) => {
			if (!session.current) throw new Error('Browser session unavailable; reconnect');
			const job = await submit(session.current.csrf, operation, payload);
			await refresh();
			return job;
		},
		[refresh],
	);
	useEffect(() => {
		let stopped = false;
		let timer: ReturnType<typeof setTimeout>;
		const poll = async () => {
			if (stopped) return;
			if (!document.hidden)
				try {
					const next = await api<Status>('/api/status');
					if (!stopped) {
						snapshot.current = next;
						setStatus(next);
						setServiceError('');
					}
				} catch {
					if (!stopped) {
						setServiceError('Service unavailable · reconnecting');
						previews.markStale();
						announce('Service unavailable · reconnecting');
					}
				}
			if (!stopped) timer = setTimeout(poll, document.hidden ? 1000 : 500);
		};
		const visible = () => {
			if (!document.hidden) {
				previews.markStale();
				void api<Status>('/api/status')
					.then((next) => {
						if (!stopped) {
							snapshot.current = next;
							setStatus(next);
						}
					})
					.catch(() => {});
			}
		};
		document.addEventListener('visibilitychange', visible);
		void api<{ csrf: string }>('/api/session')
			.then((result) => {
				if (!stopped) {
					session.current = result;
					previews.start(() => snapshot.current);
				}
			})
			.catch((error) => {
				if (!stopped) announce(String(error.message));
			});
		void poll();
		return () => {
			stopped = true;
			clearTimeout(timer);
			previews.stop();
			document.removeEventListener('visibilitychange', visible);
		};
	}, [previews]);
	useEffect(() => {
		previews.prune(status.cameras.map((c) => c.identity));
	}, [previews, status.cameras]);
	const value = useMemo(
		() => ({ selections, read, status, serviceError, previews, message, announce, refresh, mutate }),
		[selections, read, status, serviceError, previews, message, refresh, mutate],
	);
	return <Context value={value}>{children}</Context>;
}
export function useDashboard() {
	const value = useContext(Context);
	if (!value) throw new Error('DashboardProvider required');
	return value;
}
export { errorMessage } from './errors';
