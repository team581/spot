import { createFileRoute, useMatchRoute } from '@tanstack/react-router';
import Calibration from '../pages/Calibration';
// One layout keeps the calibration operation mounted while switching tabs.
export const Route = createFileRoute('/calibration')({
	component: () => <Calibration results={Boolean(useMatchRoute()({ to: '/calibration/results' }))} />,
});
