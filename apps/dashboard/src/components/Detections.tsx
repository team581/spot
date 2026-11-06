import { useStatus } from '../queries';
import { usePreview, previewData, currentFrame } from './Feed';
import { fmt, Panel } from './common';
import type { Camera } from '../types';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
const REASONS: Record<string, string> = {
	'tag-policy-excluded': 'Not selected by robot code',
	UNKNOWN_TAG_ID: 'Not in field layout',
	NO_FIELD_LAYOUT: 'No field layout loaded',
	NO_CALIBRATION: 'Camera not calibrated',
};
function reasonLabel(reason?: string) {
	if (!reason) return undefined;
	if (reason.startsWith('POSE_SOLVE_FAILED')) return 'Pose solve failed';
	return REASONS[reason] ?? reason;
}
export function Detections({ camera: c }: { camera: Camera }) {
	const status = useStatus(),
		view = usePreview(c.identity),
		data = previewData(view),
		fresh = currentFrame(view, c, status);
	const tags = fresh ? (data?.tags ?? []) : [],
		candidates = fresh ? (data?.candidates ?? []) : [],
		rejected = reasonLabel(tags.find((tag) => tag.reason)?.reason);
	return (
		<Panel title="Detections">
			<p id="pose-state" role="status" className="text-muted-foreground">
				{!c.calibrated
					? 'Pose unavailable: calibrate this camera. Tags can be detected without a calibration, but distance and pose need valid intrinsics.'
					: !fresh
						? 'Waiting for a current detection frame before showing a pose.'
						: candidates.length
							? 'Local camera pose available.'
							: rejected
								? `No pose solved for this frame: ${rejected.toLowerCase()}.`
								: 'No pose solved for this frame. Check tag visibility, the field layout and solver diagnostics.'}
			</p>
			<Table>
				<TableHeader>
					<TableRow>
						<TableHead>ID</TableHead>
						<TableHead>Range</TableHead>
						<TableHead>Error</TableHead>
						<TableHead>Used</TableHead>
					</TableRow>
				</TableHeader>
				<TableBody id="detections">
					{tags.length ? (
						tags.map((tag) => (
							<TableRow key={tag.id}>
								<TableCell>{tag.id}</TableCell>
								<TableCell>{tag.distance_m != null ? fmt(tag.distance_m) + ' m' : '—'}</TableCell>
								<TableCell>{tag.error_px != null ? fmt(tag.error_px, 2) + ' px' : '—'}</TableCell>
								<TableCell title={tag.reason}>{tag.used ? '✓' : (reasonLabel(tag.reason) ?? '—')}</TableCell>
							</TableRow>
						))
					) : (
						<TableRow>
							<TableCell colSpan={4} className="text-muted-foreground">
								{fresh ? 'No tags in this frame' : 'Waiting for current detection frame'}
							</TableCell>
						</TableRow>
					)}
				</TableBody>
			</Table>
			<Collapsible>
				<CollapsibleTrigger className="text-muted-foreground hover:text-foreground">
					Solver candidates
				</CollapsibleTrigger>
				<CollapsibleContent>
					<pre className="mt-2 overflow-auto rounded-md bg-muted p-2 text-xs">
						{JSON.stringify(candidates, null, 2)}
					</pre>
				</CollapsibleContent>
			</Collapsible>
		</Panel>
	);
}
