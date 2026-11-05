import { useEffect, useReducer, useState } from 'react';
import { useDashboard } from '../dashboard';
import { LiveTuner } from '../state/editing';
import type { Camera, Status, Values } from '../types';
const allowed = (status: Status, id: string): Values =>
	Object.fromEntries(
		(status.cameras.find((c) => c.identity === id)?.controls ?? [])
			.filter((c) => c.allowed)
			.map((c) => [c.name, c.value]),
	);
export function useTuner(camera: Camera) {
	const { status, read, mutate, refresh } = useDashboard();
	const [, redraw] = useReducer((n) => n + 1, 0);
	const [tuner] = useState(
		() =>
			new LiveTuner(
				allowed(status, camera.identity),
				status.revision,
				async (values, revision) => {
					const job = await mutate(camera.logical_name ? 'camera/tune' : 'device/tune', {
						...(camera.logical_name ? { name: camera.logical_name } : { identity: camera.identity }),
						values,
						revision,
					});
					const current = allowed(read(), camera.identity);
					return {
						revision: job.revision,
						values: Object.fromEntries(
							Object.keys(current).map((name) => [name, job.controls?.[name] ?? current[name]]),
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
			const result = await mutate(camera.logical_name ? 'camera/tune' : 'device/tune', {
				...(camera.logical_name ? { name: camera.logical_name } : { identity: camera.identity }),
				reset: true,
				revision: read().revision,
			});
			return { revision: result.revision, values: allowed(read(), camera.identity) };
		});
	const reconcile = async () => {
		try {
			const current = await refresh();
			tuner.reconcile(allowed(current, camera.identity), current.revision);
		} catch (error) {
			tuner.reject(error);
		}
	};
	return { tuner, history, reset, reconcile };
}
