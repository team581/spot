import { QueryClient, useMutation } from '@tanstack/react-query';
import createQueryClient from 'openapi-react-query';
import { client } from './api';
import type { Json, Overrides } from './overrides';
import { setOverride } from './overrides';

export const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
export const $api = createQueryClient(client);

export const useStatus = () => $api.useQuery('get', '/api/status', undefined, { refetchInterval: 1000 });
export const useDevices = () => $api.useQuery('get', '/api/devices', undefined, { refetchInterval: 2000 });
export const useConfig = () => $api.useQuery('get', '/api/config', undefined, { refetchInterval: 2000 });
export const useSettings = () => $api.useQuery('get', '/api/settings');
export const useNetwork = () => $api.useQuery('get', '/api/network', undefined, { refetchInterval: 1000 });
export const useSystem = () => $api.useQuery('get', '/api/system', undefined, { refetchInterval: 1000 });
export const useRecordings = () => $api.useQuery('get', '/api/recordings', undefined, { refetchInterval: 5000 });

export const useSaveSettings = () =>
	$api.useMutation('put', '/api/settings', {
		onSuccess: (data) => queryClient.setQueryData($api.queryOptions('get', '/api/settings').queryKey, data),
	});

type Edit = (overrides: Overrides) => Overrides;
/**
 * Writes overrides by editing the latest ones. Edits run one at a time, so each builds on the last.
 * The mutation's error holds the service's reason when the merged config would be invalid.
 */
export function useEditOverrides() {
	const configKey = $api.queryOptions('get', '/api/config').queryKey;
	const mutation = useMutation({
		scope: { id: 'overrides' },
		mutationFn: async (edit: Edit) => {
			const current = (queryClient.getQueryData<{ overrides: object }>(configKey)?.overrides ?? {}) as Overrides;
			return (await client.PUT('/api/config/overrides', { body: edit(current) })).data;
		},
		onSuccess: (view) => {
			queryClient.setQueryData(configKey, view);
			void queryClient.invalidateQueries({ queryKey: $api.queryOptions('get', '/api/status').queryKey });
			void queryClient.invalidateQueries({ queryKey: $api.queryOptions('get', '/api/devices').queryKey });
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
