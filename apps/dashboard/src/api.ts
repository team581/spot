import { up } from 'up-fetch';
import type { components, paths } from './api.gen';

type MutationPath = {
	[P in keyof paths]: paths[P] extends { post: { requestBody: object } } ? P : never;
}[keyof paths];
export type OperationName = MutationPath extends `/api/${infer N}` ? N : never;
type Operation<N extends OperationName> = paths[`/api/${N}`]['post'];
export type OperationPayload<N extends OperationName> = Operation<N>['requestBody']['content']['application/json'];
export type OperationResult<N extends OperationName> = Operation<N>['responses'][200]['content']['application/json'];
export type Applied = components['schemas']['Applied'];

/** Same-origin JSON client. Rejections carry the service's `error` message. */
export const api = up(
	(input: RequestInfo | URL, init?: RequestInit) => fetch(input, init),
	() => ({
		baseUrl: location.origin,
		credentials: 'same-origin',
		parseRejected: async (response: Response) => new Error((await response.json()).error || `HTTP ${response.status}`),
	}),
);

/** Resolves only after the runtime applies the operation. */
export const submit = <N extends OperationName>(operation: N, payload: OperationPayload<N>) =>
	api<OperationResult<N>>(`/api/${operation}`, { method: 'POST', body: payload });
