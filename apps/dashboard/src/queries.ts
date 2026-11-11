import { QueryClient, useMutation, useQuery } from '@tanstack/react-query';
import { client, unwrap } from './api';
import type { Json, Overrides } from './overrides';
import { setOverride } from './overrides';

export const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

export const useStatus = () =>
	useQuery({ queryKey: ['status'], queryFn: () => unwrap(client.GET('/api/status')), refetchInterval: 1000 });
export const useDevices = () =>
	useQuery({ queryKey: ['devices'], queryFn: () => unwrap(client.GET('/api/devices')), refetchInterval: 2000 });
export const useConfig = () =>
	useQuery({ queryKey: ['config'], queryFn: () => unwrap(client.GET('/api/config')), refetchInterval: 2000 });
export const useSettings = () =>
	useQuery({ queryKey: ['settings'], queryFn: () => unwrap(client.GET('/api/settings')) });
export const useNetwork = () =>
	useQuery({ queryKey: ['network'], queryFn: () => unwrap(client.GET('/api/network')), refetchInterval: 1000 });
export const useSystem = () =>
	useQuery({ queryKey: ['system'], queryFn: () => unwrap(client.GET('/api/system')), refetchInterval: 1000 });
export const useRecordings = () =>
	useQuery({ queryKey: ['recordings'], queryFn: () => unwrap(client.GET('/api/recordings')), refetchInterval: 5000 });

type Edit = (overrides: Overrides) => Overrides;
/**
 * Writes overrides by editing the latest ones. Edits run one at a time, so each builds on the last.
 * The mutation's error holds the service's reason when the merged config would be invalid.
 */
export function useEditOverrides() {
	const mutation = useMutation({
		scope: { id: 'overrides' },
		mutationFn: async (edit: Edit) => {
			const current = (queryClient.getQueryData<{ overrides: object }>(['config'])?.overrides ?? {}) as Overrides;
			return unwrap(client.PUT('/api/config/overrides', { body: edit(current) }));
		},
		onSuccess: (view) => {
			queryClient.setQueryData(['config'], view);
			void queryClient.invalidateQueries({ queryKey: ['status'] });
			void queryClient.invalidateQueries({ queryKey: ['devices'] });
		},
	});
	return {
		...mutation,
		/** Sets each `[path, value]` pair; `null` removes the key from the robot config. */
		set: (changes: [string[], Json][], options?: { onSettled?: () => void }) =>
			mutation.mutate(
				(overrides) => changes.reduce((next, [path, value]) => setOverride(next, path, value), overrides),
				options,
			),
	};
}
