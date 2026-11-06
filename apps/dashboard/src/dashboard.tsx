import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { PreviewStore } from './previews';
import { readStatus, useStatusQuery } from './queries';

interface Dashboard {
	selections: { results: Set<string>; history: Map<string, Set<string>> };
	previews: PreviewStore;
	message: string;
	announce: (message: string) => void;
}
const Context = createContext<Dashboard | null>(null);
export function DashboardProvider({ children }: { children: ReactNode }) {
	const [message, announce] = useState('');
	const [selections] = useState(() => ({
		results: new Set<string>(),
		history: new Map<string, Set<string>>(),
	}));
	const [previews] = useState(() => new PreviewStore());
	const { data: status, isError } = useStatusQuery();
	useEffect(() => {
		previews.start(readStatus);
		return () => previews.stop();
	}, [previews]);
	useEffect(() => {
		if (!isError) return;
		previews.markStale();
	}, [previews, isError]);
	const cameras = status?.cameras;
	useEffect(() => {
		if (cameras) previews.prune(cameras.map((c) => c.identity));
	}, [previews, cameras]);
	const value = useMemo(() => ({ selections, previews, message, announce }), [selections, previews, message]);
	return <Context value={value}>{children}</Context>;
}
export function useDashboard() {
	const value = useContext(Context);
	if (!value) throw new Error('DashboardProvider required');
	return value;
}
const serviceUnavailable = 'Service unavailable · reconnecting';
/** The status poll's failure message, or an empty string while the service responds. */
export const useServiceError = () => (useStatusQuery().isError ? serviceUnavailable : '');
export { errorMessage } from './errors';
