import { MutationCache, QueryClient, queryOptions, useMutation, useQuery } from '@tanstack/react-query';
import { api, submit, type OperationName, type OperationPayload, type OperationResult } from './api';
import { initialStatus, type Status } from './types';

const statusQuery = queryOptions({
	queryKey: ['status'],
	queryFn: () => api<Status>('/api/status'),
	refetchInterval: 500,
	retry: false,
});

export const queryClient = new QueryClient({
	// Operations change service state, so each resolves only after status reflects it.
	mutationCache: new MutationCache({
		onSuccess: () => queryClient.invalidateQueries({ queryKey: statusQuery.queryKey }),
	}),
});

/** Settles after the first status read so pages mount with real cameras; errors surface through `useStatusQuery`. */
export const loadStatus = () =>
	queryClient.ensureQueryData(statusQuery).then(
		() => undefined,
		() => undefined,
	);
export const useStatusQuery = () => useQuery(statusQuery);
export const useStatus = () => useStatusQuery().data ?? initialStatus;
export const useCamera = (id: string) => useStatus().cameras.find((c) => c.identity === id);
/** Latest status for async handlers that outlive the render that started them. */
export const readStatus = () => queryClient.getQueryData(statusQuery.queryKey) ?? initialStatus;
export const refreshStatus = () => queryClient.fetchQuery({ ...statusQuery, staleTime: 0 });

type Operation<N extends OperationName> = { [K in N]: { operation: K; payload: OperationPayload<K> } }[N];
/** Runs service operations; narrow `N` when the caller needs that operation's result type. */
export const useOperation = <N extends OperationName = OperationName>() =>
	useMutation({
		mutationFn: ({ operation, payload }: Operation<N>) =>
			submit<N>(operation, payload as OperationPayload<N>) as Promise<OperationResult<N>>,
	});

/** Pending and error state for a multi-step handler; it refreshes status like any operation. */
export const useTask = () => useMutation({ mutationFn: (run: () => Promise<void>) => run() });
