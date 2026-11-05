import { useEffect, useReducer, useState } from 'react';
import { readStatus, refreshStatus, useOperation, useStatus } from '../queries';
import { LiveTuner } from '../state/editing';
import type { Camera, Status, Values } from '../types';
const allowed = (status: Status, id: string): Values =>
	Object.fromEntries(
		(status.cameras.find((c) => c.identity === id)?.controls ?? [])
			.filter((c) => c.allowed)
			.map((c) => [c.name, c.value]),
	);
export function useTuner(camera: Camera) {
	const status = useStatus();
	const { mutateAsync } = useOperation<'camera/tune' | 'device/tune'>();
	const tune = (payload: { values?: Values; reset?: boolean; revision: string }) =>
		camera.logical_name
			? mutateAsync({ operation: 'camera/tune', payload: { name: camera.logical_name, ...payload } })
			: mutateAsync({ operation: 'device/tune', payload: { identity: camera.identity, ...payload } });
	const [, redraw] = useReducer((n) => n + 1, 0);
	const [tuner] = useState(
		() =>
			new LiveTuner(
				allowed(status, camera.identity),
				status.revision,
				async (values, revision) => {
					const applied = await tune({ values, revision });
					const current = allowed(readStatus(), camera.identity);
					return {
						revision: applied.revision,
						values: Object.fromEntries(
							Object.keys(current).map((name) => [name, applied.controls?.[name] ?? current[name]]),
						),
					};
				},
				() => redraw(),
			),
	);
	useEffect(() => {
		tuner.observe(allowed(status, camera.identity), status.revision);
		redraw();
	}, [tuner, status, camera.identity]);
	useEffect(() => () => tuner.dispose(), [tuner]);
	const history = (direction: 'undo' | 'redo') => tuner.applyHistory(direction);
	const reset = () =>
		tuner.reset(async () => {
			const applied = await tune({ reset: true, revision: readStatus().revision });
			return { revision: applied.revision, values: allowed(readStatus(), camera.identity) };
		});
	const reconcile = async () => {
		try {
			const current = await refreshStatus();
			tuner.reconcile(allowed(current, camera.identity), current.revision);
		} catch (error) {
			tuner.reject(error);
		}
	};
	return { tuner, history, reset, reconcile };
}
