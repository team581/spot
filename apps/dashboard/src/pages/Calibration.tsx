import { readStatus, useOperation, useStatus } from '../queries';
import { Feedback, LinkTabs, PageTitle } from '../components/common';
import { Button } from '@/components/ui/button';
import Capture from './calibration/Capture';
import Results from './calibration/Results';
export type CalibrationOperation = ReturnType<typeof useOperation>;
export default function Calibration({ results }: { results: boolean }) {
	const status = useStatus(),
		operation = useOperation();
	return (
		<>
			<PageTitle>Calibration</PageTitle>
			<LinkTabs
				tabs={[
					{ href: '#calibration', label: 'Capture', active: !results },
					{ href: '#calibration/results', label: 'Results / history', active: results },
				]}
			>
				<Button
					variant="outline"
					onClick={() =>
						operation.mutate({ operation: 'calibration/pause-all', payload: { revision: readStatus().revision } })
					}
				>
					Pause all
				</Button>
				<Button
					variant="outline"
					onClick={() =>
						operation.mutate({ operation: 'calibration/reset', payload: { revision: readStatus().revision } })
					}
				>
					Reset session
				</Button>
			</LinkTabs>
			<Feedback id="calibration-lock">{status.lock_reason}</Feedback>
			<Feedback id="page-feedback">{operation.error?.message}</Feedback>
			{results ? <Results /> : <Capture operation={operation} />}
		</>
	);
}
