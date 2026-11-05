import { readStatus, useOperation, useStatus } from '../queries';
import Capture from './calibration/Capture';
import Results from './calibration/Results';
export type CalibrationOperation = ReturnType<typeof useOperation>;
export default function Calibration({ results }: { results: boolean }) {
	const status = useStatus(),
		operation = useOperation();
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
					<button
						onClick={() =>
							operation.mutate({ operation: 'calibration/pause-all', payload: { revision: readStatus().revision } })
						}
					>
						Pause all
					</button>
					<button
						onClick={() =>
							operation.mutate({ operation: 'calibration/reset', payload: { revision: readStatus().revision } })
						}
					>
						Reset session
					</button>
				</div>
			</div>
			<p className="lock" id="calibration-lock">
				{status.lock_reason}
			</p>
			<p className="feedback" id="page-feedback">
				{operation.error?.message}
			</p>
			{results ? <Results /> : <Capture operation={operation} />}
		</>
	);
}
