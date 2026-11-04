import { useState } from 'react';
import { useDashboard, errorMessage } from '../dashboard';
import type { Job } from '../types';
import Capture from './calibration/Capture';
import Results from './calibration/Results';
export type Action = (operation: string, payload?: Record<string, unknown>) => Promise<Job | null>;
export default function Calibration({ results }: { results: boolean }) {
	const { status, read, mutate } = useDashboard(),
		[error, setError] = useState('');
	const action: Action = async (operation, payload = {}) => {
		try {
			return await mutate('calibration/' + operation, { ...payload, revision: read().revision });
		} catch (e) {
			setError(errorMessage(e));
			return null;
		}
	};
	return (
		<>
			<h1>Calibration</h1>
			<div className="tabs">
				<a href="#calibration" className={!results ? 'active' : ''}>
					Capture
				</a>
				<a href="#calibration/results" className={results ? 'active' : ''}>
					Results / history
				</a>
				<div className="actions">
					<button onClick={() => void action('pause-all')}>Pause all</button>
					<button onClick={() => void action('reset')}>Reset session</button>
				</div>
			</div>
			<p className="lock" id="calibration-lock">
				{status.lock_reason}
			</p>
			<p className="feedback" id="page-feedback">
				{error}
			</p>
			{results ? <Results action={action} /> : <Capture action={action} onError={setError} />}
		</>
	);
}
