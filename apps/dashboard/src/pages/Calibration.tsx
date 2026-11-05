import { readStatus, useOperation } from '../queries';
import { Feedback, LinkTabs, PageTitle, TabLink } from '../components/common';
import { Button } from '@/components/ui/button';
import Capture from './calibration/Capture';
import Results from './calibration/Results';
export type CalibrationOperation = ReturnType<typeof useOperation>;
export default function Calibration({ results }: { results: boolean }) {
	const operation = useOperation();
	return (
		<>
			<PageTitle>Calibration</PageTitle>
			<LinkTabs
				tabs={
					<>
						<TabLink to="/calibration" activeOptions={{ exact: true }}>
							Capture
						</TabLink>
						<TabLink to="/calibration/results">Results / history</TabLink>
					</>
				}
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
			<Feedback id="page-feedback">{operation.error?.message}</Feedback>
			{results ? <Results /> : <Capture operation={operation} />}
		</>
	);
}
