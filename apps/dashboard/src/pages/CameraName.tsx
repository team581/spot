import { Link } from '@tanstack/react-router';
import { useState } from 'react';
import { useDashboard } from '../dashboard';
import { useOperation, useStatus } from '../queries';
import { availableCameraNames } from '../state/editing';
import { Feed } from '../components/Feed';
import { CameraSelector, Feedback, PageTitle, Panel } from '../components/common';
import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Separator } from '@/components/ui/separator';
import type { Camera } from '../types';
export default function CameraName({ camera: c }: { camera: Camera }) {
	const { announce } = useDashboard(),
		status = useStatus(),
		operation = useOperation(),
		busy = operation.isPending,
		available = availableCameraNames(status.names, status.cameras, c.identity);
	const [choice, setChoice] = useState(''),
		[confirmed, setConfirmed] = useState(false);
	return (
		<>
			<PageTitle id="camera-title">{c.name}</PageTitle>
			<CameraSelector cameras={status.cameras} id={c.identity} />
			<div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
				<Feed id={c.identity} />
				<Panel title="Camera name">
					<p className="inline-flex items-center gap-1 text-warning">
						<TriangleAlert className="size-3.5" aria-hidden /> Not configured in code
					</p>
					<Label htmlFor="camera-name">Name</Label>
					<NativeSelect
						id="camera-name"
						className="w-full"
						value={available.includes(choice) ? choice : (available[0] ?? '')}
						onChange={(e) => setChoice(e.target.value)}
					>
						{available.length ? (
							available.map((name) => <NativeSelectOption key={name}>{name}</NativeSelectOption>)
						) : (
							<NativeSelectOption value="">No names available in robot code</NativeSelectOption>
						)}
					</NativeSelect>
					<Label>
						<Checkbox checked={confirmed} onCheckedChange={setConfirmed} /> This preview matches the physical camera
					</Label>
					<Button
						id="rename"
						disabled={busy || Boolean(status.lock_reason) || !c.connected || !available.length || !confirmed}
						onClick={() =>
							operation.mutate(
								{
									operation: 'device/name',
									payload: {
										identity: c.identity,
										name: available.includes(choice) ? choice : available[0],
										revision: status.revision,
									},
								},
								{ onSuccess: () => announce('Camera renamed') },
							)
						}
					>
						Rename
					</Button>
					<Separator />
					<p>Use this camera without a robot profile for tuning and calibration.</p>
					<Button
						variant="outline"
						disabled={busy}
						onClick={() =>
							operation.mutate({
								operation: 'device/setup',
								payload: { identity: c.identity, revision: status.revision },
							})
						}
					>
						Open standalone camera setup
					</Button>
					<Feedback id="naming-lock">
						{status.lock_reason ||
							(status.fresh
								? 'Confirm this preview matches the physical camera'
								: 'Cached code names · standalone setup')}
					</Feedback>
					<Feedback id="page-feedback">{operation.error?.message}</Feedback>
					<Link to="/help/$" params={{ _splat: 'operator/cameras/' }} hash="assign-cameras">
						Configure camera names in robot code
					</Link>
				</Panel>
			</div>
		</>
	);
}
